import tensorflow as tf
import random
import ssbm
import ctypes
import tf_lib as tfl
import util
import ctype_util as ct
import numpy as np
import embed
from dqn import DQN
from actor_critic import ActorCritic
import config
from operator import add, sub
from enum import Enum
from reward import computeRewards

class Mode(Enum):
  TRAIN = 0
  PLAY = 1

models = {model.__name__ : model for model in [DQN, ActorCritic]}

class Model:
  def __init__(self, model="DQN", path=None, mode = Mode.TRAIN, debug = False, **kwargs):
    print("Creating model:", model)
    modelType = models[model]
    self.path = path
    
    # TODO: take into account mode
    with tf.name_scope('input'):
      self.input_states = ct.inputCType(ssbm.GameMemory, [None], "states")

      # player 2's controls
      self.input_actions = tf.placeholder(tf.int32, [None], "actions")
      #experience_length = tf.shape(input_actions)

    self.embedded_states = embed.embedGame(self.input_states)
    self.state_size = self.embedded_states.get_shape()[-1].value # TODO: precompute

    self.embedded_actions = embed.embedAction(self.input_actions)
    self.action_size = self.embedded_actions.get_shape()[-1].value

    # instantaneous rewards for all but the first state
    self.rewards = tf.placeholder(tf.float32, [None], name='rewards')

    self.global_step = tf.Variable(0, name='global_step', trainable=False)

    self.model = modelType(self.state_size, self.action_size, self.global_step)

    with tf.name_scope('train'):
      loss, stats = self.model.getLoss(self.embedded_states, self.embedded_actions, self.rewards)
      stats.append(('global_step', self.global_step))
      self.stat_names, self.stat_tensors = zip(*stats)

      optimizer = tf.train.AdamOptimizer(10.0 ** -4)
      # train_q = opt.minimize(qLoss, global_step=global_step)
      # opt = tf.train.GradientDescentOptimizer(0.0)
      #grads_and_vars = opt.compute_gradients(qLoss)
      grads_and_vars = optimizer.compute_gradients(loss)
      grads_and_vars = [(g, v) for g, v in grads_and_vars if g is not None]
      self.trainer = optimizer.apply_gradients(grads_and_vars, global_step=self.global_step)
      self.runOps = self.stat_tensors + (self.trainer,)

    with tf.name_scope('policy'):
      # TODO: policy might share graph structure with loss?
      self.policy = self.model.getPolicy(self.embedded_states)

    # don't eat up cpu cores
    # or gpu memory
    self.sess = tf.Session(
      config=tf.ConfigProto(
        inter_op_parallelism_threads=1,
        intra_op_parallelism_threads=1,
        use_per_session_threads=True,
        gpu_options = tf.GPUOptions(per_process_gpu_memory_fraction=0.3)
      )
    )
    
    self.debug = debug
    
    self.saver = tf.train.Saver(tf.all_variables())

  def act(self, state, verbose=False):
    feed_dict = ct.feedCTypes(ssbm.GameMemory, 'input/states', [state])
    return self.model.act(self.sess.run(self.policy, feed_dict), verbose)

  #summaryWriter = tf.train.SummaryWriter('logs/', sess.graph)
  #summaryWriter.flush()

  def debugGrads():
    gs = sess.run([gv[0] for gv in grads_and_vars], feed_dict)
    vs = sess.run([gv[1] for gv in grads_and_vars], feed_dict)
    #   loss = sess.run(qLoss, feed_dict)
    #act_qs = sess.run(qs, feed_dict)
    #act_qs = list(map(util.compose(np.sort, np.abs), act_qs))

    #t = sess.run(temperature)
    #print("Temperature: ", t)
    #for i, act in enumerate(act_qs):
    #  print("act_%d"%i, act)
    #print("grad/param(action)", np.mean(np.abs(gs[0] / vs[0])))
    #print("grad/param(stage)", np.mean(np.abs(gs[2] / vs[2])))

    print("param avg and max")
    for g, v in zip(gs, vs):
      abs_v = np.abs(v)
      abs_g = np.abs(g)
      print(v.shape, np.mean(abs_v), np.max(abs_v), np.mean(abs_g), np.max(abs_g))

    print("grad/param avg and max")
    for g, v in zip(gs, vs):
      ratios = np.abs(g / v)
      print(np.mean(ratios), np.max(ratios))
    #print("grad", np.mean(np.abs(gs[4])))
    #print("param", np.mean(np.abs(vs[0])))

    # if step_index == 10:
    import ipdb; ipdb.set_trace()

  def train(self, filename, steps=1):
    #state_actions = ssbm.readStateActions(filename)
    #feed_dict = feedStateActions(state_actions)
    feed_dict = ssbm.readStateActions_pickle(filename)

    # FIXME: we feed the inputs in on each iteration, which might be inefficient.
    for step_index in range(steps):
      if self.debug:
        self.debugGrads()
      
      # last result is trainer
      results = self.sess.run(self.runOps, feed_dict)[:-1]
      util.zipWith(print, self.stat_names, results)

    return sum(feed_dict['rewards:0'])

  def save(self):
    import os
    os.makedirs(self.path, exist_ok=True)
    print("Saving to", self.path)
    self.saver.save(self.sess, self.path + "snapshot")

  def restore(self):
    self.saver.restore(self.sess, self.path + "snapshot")

  def init(self):
    self.sess.run(tf.initialize_all_variables())

