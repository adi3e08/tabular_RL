import numpy as np
import torch
import torch.multiprocessing as mp
import torch.nn.functional as F
from torch.utils.tensorboard import SummaryWriter
import os
import argparse
import gym
from copy import deepcopy

# Fully Connected Joint Actor Critic network
class Pi_V_FC(torch.nn.Module):
    def __init__(self, state_size, action_size):
        super(Pi_V_FC, self).__init__()
        self.fc1 = torch.nn.Linear(state_size, 64)
        self.fc2 = torch.nn.Linear(64, 64)
        self.pi = torch.nn.Linear(64, action_size)
        self.v = torch.nn.Linear(64, 1)
        self.distribution = torch.distributions.Categorical        
    def forward(self, x):
        y1 = F.relu(self.fc1(x))
        y2 = F.relu(self.fc2(y1))
        probs = F.softmax(self.pi(y2), dim=1)
        values = self.v(y2).view(-1)
        return probs, values

class Worker(mp.Process):
    def __init__(self, process_num, arglist, mp_lock, global_episode, global_mb, results_queue, rollouts_queue, ep_r_queue, msg_queue, model, device,config_dir=""):
        super(Worker, self).__init__()
        
        self.name = str(process_num)
        self.arglist = arglist
        self.mp_lock = mp_lock
        self.global_episode = global_episode
        self.global_mb = global_mb
        self.results_queue = results_queue
        self.rollouts_queue = rollouts_queue
        self.ep_r_queue = ep_r_queue
        self.msg_queue = msg_queue
        self.model = model
        self.optimizer = torch.optim.Adam(self.model.parameters(), lr=self.arglist.lr)
        self.device = device

    def run(self):
        self.env = make_env()
        self.env.seed(int(self.name))

        l_ep = 0
        new_batch = True  
        while l_ep < self.arglist.episodes_per_worker:
            t = 0
            ep_r = 0.0
            o = self.env.reset()
            while True:
                probs, values_ = self.model(torch.tensor(o, dtype=torch.float, device=self.device).unsqueeze(0))
                m = self.model.distribution(probs)
                index = m.sample()                 
                if new_batch:
                    log_probs = m.log_prob(index)
                    entrops = m.entropy()
                    values = values_
                    R = []
                    new_batch = False                    
                else:
                    log_probs = torch.cat((log_probs,m.log_prob(index)),dim=0)
                    entrops = torch.cat((entrops,m.entropy()),dim=0)
                    values = torch.cat((values,values_),dim=0)
                a = index[0].item()
                o_1, r, done, info = self.env.step(a)
                t += 1
                ep_r += r
                R.append(r)
                o = o_1
                if (t % self.arglist.update_every == 0 or done):  # update global and assign to local net
                    # sync
                    mb = deepcopy(self.global_mb.value)
                    if done:
                        v_s_ = 0.0               # terminal
                    else:
                        with torch.set_grad_enabled(False): 
                            _, next_values = self.model(torch.tensor(o_1, dtype=torch.float, device=self.device).unsqueeze(0))
                        v_s_ = next_values[0].item()

                    v_targets = []
                    for r in R[::-1]:    # reverse buffer r
                        v_s_ = r + self.arglist.gamma * v_s_
                        v_targets.append(v_s_)
                    v_targets.reverse()
                    v_targets = torch.tensor(v_targets, dtype=torch.float, device=self.device)
                    td = v_targets - values
                    a_loss = - (log_probs * td.detach() + 0.01 * entrops)                                 
                    c_loss = td.pow(2)

                    loss = (a_loss + 0.5 * c_loss).sum()
                    self.optimizer.zero_grad()
                    loss.backward()                
                    gradients = [param.grad.clone() for param in self.model.parameters()]
                    rollouts = [self.name, mb, gradients]
                    self.rollouts_queue.put(rollouts)
                    # print("W",self.name,"episode",l_ep,"sent MB ",mb)

                    new_batch = True
                    while True :
                        if self.global_mb.value > mb:
                            break

                if done :
                    with self.mp_lock:
                        ep_summary = [deepcopy(self.global_episode.value), ep_r]
                        self.global_episode.value += 1
                    self.ep_r_queue.put(ep_summary)
                    l_ep += 1            
                    break
        with self.mp_lock:
            self.msg_queue[int(self.name)] = 0


class A2C():
    def __init__(self, arglist):

        self.arglist = arglist
        self.device = torch.device("cpu")
        # self.device = torch.device("cuda:0")
        self.mp_lock = mp.Lock()
        self.exp_dir = os.path.join("./log", self.arglist.exp_name)
        self.model_dir = os.path.join(self.exp_dir, "models")
        self.tensorboard_dir = os.path.join(self.exp_dir, "tensorboard")
        if os.path.exists("./log"):
            pass            
        else:
            os.mkdir("./log")
        os.mkdir(self.exp_dir)
        os.mkdir(os.path.join(self.tensorboard_dir))
        os.mkdir(self.model_dir)

        self.env = make_env()
        self.worker_processes = self.arglist.worker_processes    
        self.model = Pi_V_FC(self.env.state_size,self.env.action_size).to(self.device)

    def save_checkpoint(self, name):
        checkpoint = {'model' : self.model.state_dict()}
        torch.save(checkpoint, os.path.join(self.model_dir, name))

    def load_checkpoint(self, path):
        checkpoint = torch.load(path)
        self.model.load_state_dict(checkpoint['model'])

    def train(self):

        self.model.share_memory()
        self.optimizer = torch.optim.Adam(self.model.parameters(), lr=self.arglist.lr)
           
        ep_r_queue = mp.Queue()
        rollouts_queue = mp.Queue()
        self.episode = mp.Value('i', 0)
        self.mb = mp.Value('i', 0)
        self.msg_queue = mp.Array('i', self.worker_processes)
        for wk in range(self.worker_processes):
            self.msg_queue[wk] = 1
        
        global_path = os.path.join(self.model_dir, "net_ckpt_latest")

        optimizer_worker = mp.Process(target=self.update_shared_model, args=(rollouts_queue,))
        plot_ep_r_worker = mp.Process(target=self.plot_ep_r, args=(ep_r_queue,))
        optimizer_worker.start()
        plot_ep_r_worker.start()

        processes = []
        for process_num in range(self.worker_processes):
            worker = Worker(process_num, self.arglist, self.mp_lock, self.episode, self.mb, ep_r_queue, rollouts_queue, ep_r_queue, self.msg_queue, self.model, self.device)
            worker.start()
            processes.append(worker)
        
        for i, worker in enumerate(processes):
            worker.join()
        print("Done workers")
        optimizer_worker.join()
        print("Done opts")
        plot_ep_r_worker.join()
        print("Done plots")

    def update_shared_model(self, rollouts_queue):
        """Worker that updates the shared model as rollouts get put into the queue"""
        new_batch = True
        froms = [0 for i in range(self.worker_processes)]
        while True:
            if rollouts_queue.qsize()>0:
                rollouts = rollouts_queue.get()
                name = int(rollouts[0])
                mb_id = rollouts[1]
                if mb_id == self.mb.value:
                    froms[name] = 1
                    if new_batch:
                        gradients = rollouts[2]
                        new_batch = False
                    else :
                        new_gradients = rollouts[2]
                        gradients = [grad + new_grad for grad, new_grad in zip(gradients, new_gradients)]                    
                    # print("\n Got from ",name , " mini-batch id ", mb_id)
                    if sum(self.msg_queue) == sum(froms):
                        self.optimizer.zero_grad() 
                        N_trajs = sum(froms)
                        for grad, param in zip(gradients, self.model.parameters()):
                            param._grad = grad/N_trajs             
                        # torch.nn.utils.clip_grad_norm_(self.model.parameters(), self.arglist.clip_term)
                        self.optimizer.step()
                        with self.mp_lock:
                            # print("Got MB ",self.mb.value, self.episode.value)
                            self.mb.value += 1
                        froms = [0 for i in range(self.worker_processes)]
                        new_batch = True
                del rollouts

            if sum(self.msg_queue) == 0:
                break
        # print("Done from update_shared_model")

    def eval(self, episodes):
        ep_r_list = []
        for episode in range(episodes):
            o = self.env.reset()
            ep_r = 0
            while True:
                with torch.set_grad_enabled(False):
                    probs, values_ = self.model(torch.tensor(o, dtype=torch.float, device=self.device).unsqueeze(0))
                m = self.model.distribution(probs)
                index = m.sample()                 
                a = index[0].item()   
                o_1, r, done, info = self.env.step(a)
                ep_r += r
                o = o_1
                if done:
                    ep_r_list.append(ep_r)
                    break
        return ep_r_list  

    def plot_ep_r(self,ep_r_queue):
        # global writer_reward
        writer = SummaryWriter(log_dir=self.tensorboard_dir)
        while True:            
            if ep_r_queue.qsize() > 0:
                ep_summary = ep_r_queue.get()
                episode = ep_summary[0]
                ep_r = ep_summary[1]
                writer.add_scalar('ep_r', ep_r, episode)
                if episode % self.arglist.eval_every == 0 or \
                        episode == self.arglist.worker_processes * self.arglist.episodes_per_worker -1:
                    with self.mp_lock:
                        eval_ep_r_list = self.eval(self.arglist.eval_over)
                    writer.add_scalar('eval_ep_r', np.mean(eval_ep_r_list), episode)
                    self.save_checkpoint(str(episode)+".ckpt")
                del ep_summary
            if sum(self.msg_queue) == 0:
                break
        writer.close()
        # print("Done from plot_ep_r")

def parse_args():
    parser = argparse.ArgumentParser("A2C")
    parser.add_argument("--exp-name", type=str, default="expt_1", help="name of experiment")
    parser.add_argument("--worker-processes", type=int, default=4, help="number of worker processes")
    parser.add_argument("--episodes-per-worker", type=int, default=12000, help="number of episodes")
    # Core training parameters
    parser.add_argument("--lr", type=float, default=2.5e-4, help="learning rate")
    parser.add_argument("--gamma", type=float, default=0.99, help="discount factor")
    # parser.add_argument("--clip-term", type=float, default=0.5, help="gradient clipping parameter")
    parser.add_argument("--update-every", type=int, default=4, help="train after every _ steps")
    parser.add_argument("--eval-every", type=int, default=1000, help="eval every _ episodes")
    parser.add_argument("--eval-over", type=int, default=100, help="eval over _ episodes")
    return parser.parse_args()

def make_env():
    # env = gym.make('CartPole-v1')
    # env.state_size = 4
    # env.action_size = 2
    env = gym.make('MountainCar-v0')
    env.state_size = 2
    env.action_size = 3
    return env

if __name__ == '__main__':

    try:
        mp.set_start_method('spawn')
    except RuntimeError:
        pass

    arglist = parse_args()
    a2c = A2C(arglist)
    a2c.train()