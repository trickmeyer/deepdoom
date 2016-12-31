#!/usr/bin/env python
import random
import numpy as np
import vizdoom as vd
import scipy.ndimage as Simg
import ennemies
import map_parser
from tqdm import tqdm  # NOQA

from network import tf, DRQN
from memory import ReplayMemory
from config import *  # NOQA


# Image input size
im_w, im_h = 108, 60
# Number of game features
k = 3

# Import from config
batch_size = BATCH_SIZE
sequence_length = SEQUENCE_LENGTH
n_actions = N_ACTIONS
ACTION_SET = np.eye(n_actions, dtype=np.uint32).tolist()


def create_game():
    game = vd.DoomGame()
    game.load_config("basic.cfg")

    # Ennemy detection
    walls = map_parser.parse("maps/deathmatch.txt")
    game.clear_available_game_variables()
    game.add_available_game_variable(vd.GameVariable.POSITION_X)
    game.add_available_game_variable(vd.GameVariable.POSITION_Y)
    game.add_available_game_variable(vd.GameVariable.POSITION_Z)
    game.set_labels_buffer_enabled(True)

    game.init()
    return game, walls


def play_episode(game, walls, verbose=False, epsilon=0.1, skip=1):
    game.new_episode()
    dump = []
    zoomed = np.zeros((500, im_h, im_w, 3), dtype=np.uint8)
    action = ACTION_SET[0]
    i = 0
    while not game.is_episode_finished():
        if i % skip == 0:
            # Get screen buf
            state = game.get_state()
            S = state.screen_buffer # NOQA

            # Resample to our network size
            h, w = S.shape[:2]
            Simg.zoom(S, [1. * im_h / h, 1. * im_w / w, 1], output=zoomed[len(dump)], order=0)
            S = zoomed[len(dump)] # NOQA

            game_features = ennemies.has_visible_entities(state, walls)

            # Epsilon-Greedy strat
            if np.random.rand() < epsilon:
                action = random.choice(ACTION_SET)
            else:
                action_no = sess.run(main.choice, feed_dict={
                    main.images: [[S]],
                })
                action = ACTION_SET[action_no[0][0]]

            if verbose:
                print(action)
            reward = game.make_action(action)
            dump.append((S, action, reward, game_features))
        else:
            game.make_action(action)
        i += 1
    return dump


def wrap_play_episode(i):
    game, walls = create_game()
    res = play_episode(game, walls, epsilon=1, skip=4)
    game.close()
    return res


if __name__ == '__main__':
    from os import system
    system('git show | head -1')

    print('Building main DRQN')
    main = DRQN(im_h, im_w, k, n_actions, 'main', learning_rate=LEARNING_RATE)
    # print('Building target DRQN')
    # target = DRQN(im_h, im_w, k, n_actions, 'target')
    # TODO target = main

    # initial LSTM state
    state = (np.zeros([batch_size, main.h_size]),
             np.zeros([batch_size, main.h_size]))

    saver = tf.train.Saver()

    with tf.Session() as sess:
        init = tf.global_variables_initializer()
        sess.run(init)

        try:
            saver.restore(sess, "./model.ckpt")
        except:
            import traceback
            traceback.print_exc()
            print("=== Recreate new model ! ===")

        print("Training vars:", [v.name for v in tf.trainable_variables()])

        mem = ReplayMemory(min_size=MIN_MEM_SIZE, max_size=MAX_MEM_SIZE)

        from multiprocessing import Pool, cpu_count
        cores = min(cpu_count(), MAX_CPUS)
        workers = Pool(cores)

        # 1 / Bootstrap memory
        print("--------")
        print("mem_size")
        while not mem.initialized:
            for episode in workers.map(wrap_play_episode, range(cores)):
                mem.add(episode)
            print(len(mem))

        # 2 / Replay and learn
        print("--------")
        print("training_step,loss_traning,loss_test")
        for i in range(TRAINING_STEPS):
            # Play and add new episodes to memory
            for episode in workers.map(wrap_play_episode, range(cores)):
                mem.add(episode)

            for j in range(cores):
                # Sample a batch and ingest into the NN
                samples = mem.sample(batch_size, sequence_length)
                # screens, actions, rewards, game_features
                S, A, R, F = map(np.array, zip(*samples))
                main.learn_game_features(S, F)

            training_loss = main.current_game_features_loss(S, F)
            # Sample a batch and ingest into the NN
            samples = mem.sample(batch_size, sequence_length)
            # screens, actions, rewards, game_features
            S, A, R, F = map(np.array, zip(*samples))
            test_loss = main.current_game_features_loss(S, F)
            print("{},{},{}".format(i, training_loss, test_loss))

            if i % 100 == 0:
                saver.save(sess, "./model.ckpt")

        #  3 / Play
        # print("-------")
        # game, walls = create_game()

        # DIV = 1 / 1000000
        # frames = 0
        # for i in range(QLEARNING_STEPS):
        #     if frames > 1000000:
        #         e = 0.1
        #     else:
        #         e = 0.1 + 0.9 * (1 - (frames * DIV))
        #     res = play_episode(game, walls, skip=4, epsilon=e)
        #     frames += len(res)

        # game.close()
