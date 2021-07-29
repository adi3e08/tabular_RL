# DQN

DQN - Deep Q learning with experience replay, target networks.

## References
* "Playing Atari with Deep Reinforcement Learning", Mnih et al. [Link](https://www.cs.toronto.edu/~vmnih/docs/dqn.pdf).
* "Human-level control through deep reinforcement learning", Mnih et al. [Link](https://web.stanford.edu/class/psych209/Readings/MnihEtAlHassibis15NatureControlDeepRL.pdf).

## Tested on
* [Cart Pole](https://gym.openai.com/envs/CartPole-v1/) - Move back and forth to balance a pole on a cart.

<p align="center">
Cumulative Reward (total reward collected during episode) vs Episode, during training.
</p>
<p align="center">
<img src="media/cartpole_train.png" width="75%" height="75%"/>
</p>

<p align="center">
Evaluate agent performance every 1000 episodes. Each time calculate average cumulative reward over 100 episodes.
</p>
<p align="center"> 
<img src="media/cartpole_eval.png" width="75%" height="75%"/>
</p>

<p align="center">
Trained agent
</p>
<p align="center">
<img src="media/cartpole_v1_trained.gif" width="50%" height="50%"/>
</p>

* [Mountain Car ](https://gym.openai.com/envs/MountainCar-v0/) - Move back and forth to build up enough momentum to drive up a big hill.

<p align="center">
Cumulative Reward vs Episode, during training.
</p>
<p align="center">
<img src="media/mountaincar_train.png" width="75%" height="75%"/>
</p>

<p align="center">
Evaluate agent performance every 1000 episodes. Each time calculate average cumulative reward over 100 episodes.
</p>
<p align="center">
<img src="media/mountaincar_eval.png" width="75%" height="75%"/>
</p>

<p align="center">
Trained agent
</p>
<p align="center">
<img src="media/mountain_car_v0_trained.gif" width="50%" height="50%"/>
</p>