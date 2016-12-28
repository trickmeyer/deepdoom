import tensorflow as tf
import tensorflow.contrib.slim as slim


class DRQN():
    def __init__(self, im_h, im_w, k, n_actions, scope):
        self.im_h, self.im_w, self.k = im_h, im_w, k
        self.scope, self.n_actions = scope, n_actions
        self.batch_size = tf.placeholder(tf.int32, name='batch_size')
        self.sequence_length = tf.placeholder(tf.int32, name='sequence_length')

        self.images = tf.placeholder(tf.float32, name='images',
                                     shape=[None, None, im_h, im_w, 3])
        # we'll merge all sequences in one single batch for treatment
        # but all outputs will be reshaped to [batch_size, length, ...]
        self.all_images = tf.reshape(self.images,
                                     [self.batch_size*self.sequence_length,
                                      im_h, im_w, 3])

        self._init_conv_layers()
        self._init_game_features_output()
        self._init_recurrent_part()
        self._define_loss()

    def _init_conv_layers(self):
        self.conv1 = slim.conv2d(
                self.all_images, 32, [8, 8], [4, 4], 'VALID',
                biases_initializer=None, scope=self.scope+'_conv1')
        self.conv2 = slim.conv2d(
                self.conv1, 64, [4, 4], [2, 2], 'VALID',
                biases_initializer=None, scope=self.scope+'_conv2')

    def _init_game_features_output(self):
        self.layer4 = slim.fully_connected(
                slim.flatten(self.conv2), 512, scope=self.scope+'_l4')
        self.flat_game_features = slim.fully_connected(
                self.layer4, self.k, scope=self.scope+'_l4.5')
        self.game_features = tf.reshape(self.flat_game_features, [self.batch_size, self.sequence_length, self.k])
        self.game_features_in = tf.placeholder(tf.float32, name='game_features_in', shape=[None, None, self.k])
        self.features_loss = tf.reduce_mean(tf.square(self.game_features - self.game_features_in))
        self.features_train_step = tf.train.RMSPropOptimizer(0.01).minimize(self.features_loss)

    def _init_recurrent_part(self):
        self.layer3 = tf.reshape(slim.flatten(self.conv2),
                                 [self.batch_size, self.sequence_length, 4608])
        self.h_size = 4608

        self.cell = tf.nn.rnn_cell.LSTMCell(self.h_size)
        self.state_in = self.cell.zero_state(self.batch_size, tf.float32)
        self.rnn_output, self.state_out = tf.nn.dynamic_rnn(
                self.cell,
                self.layer3,
                initial_state=self.state_in,
                dtype=tf.float32,
                scope=self.scope+'_RNN/')

        self.rnn_output = tf.reshape(self.rnn_output, [-1, self.h_size])
        self.Q = slim.fully_connected(
            self.rnn_output, self.n_actions, scope=self.scope+'_actions',
            activation_fn=None)
        self.Q = tf.reshape(self.Q,
                [self.batch_size, self.sequence_length, self.n_actions])
        self.choice = tf.argmax(self.Q, 2)

    def _define_loss(self):
        self.gamma = tf.placeholder(tf.float32, name='gamma')
        self.target_q = tf.placeholder(tf.float32, name='target_q',
                                       shape=[None, None, self.n_actions])
        self.rewards = tf.placeholder(tf.float32, name='rewards',
                                      shape=[None, None])
        y = self.rewards + self.gamma * tf.reduce_sum(
                tf.one_hot(self.choice, self.n_actions) * self.target_q, 2)
        Qas = tf.reduce_sum(tf.one_hot(self.choice, self.n_actions) * self.Q, 2)
        self.loss = tf.reduce_mean(tf.square(y-Qas))
        self.train_step = tf.train.RMSPropOptimizer(0.001).minimize(self.loss)
