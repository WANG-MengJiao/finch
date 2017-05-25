import tensorflow as tf
import numpy as np
import math


class HighwayClassifier:
    def __init__(self, n_in, n_out, n_highway=10, highway_units=64, sess=tf.Session()):
        """
        Parameters:
        -----------
        n_in: int
            Input dimensions (number of features)
        n_out: int
            Output dimensions
        sess: object
            tf.Session() object 
        """
        self.n_in = n_in
        self.n_highway = n_highway
        self.highway_units = highway_units
        self.n_out = n_out
        self.sess = sess
        self.current_layer = None
        self.build_graph()
    # end constructor


    def build_graph(self):
        self.add_input_layer()
        self.add_fc(self.highway_units)

        for n in range(self.n_highway):
            self.add_highway(n)
        
        self.add_output_layer()
        self.add_backward_path()
    # end method build_graph


    def add_input_layer(self):
        self.X = tf.placeholder(tf.float32, [None, self.n_in])
        self.Y = tf.placeholder(tf.float32, [None, self.n_out])
        self.keep_prob = tf.placeholder(tf.float32)
        self.train_flag = tf.placeholder(tf.bool)
        self.lr = tf.placeholder(tf.float32)
        self.current_layer = self.X
    # end method add_input_layer


    def add_fc(self, out_dim):
        Y = tf.layers.dense(self.current_layer, out_dim)
        Y = tf.contrib.layers.batch_norm(Y, is_training=self.train_flag)
        Y = tf.nn.relu(Y)
        Y = tf.nn.dropout(Y, self.keep_prob)
        self.current_layer = Y
    # end add_fc


    def add_highway(self, n, carry_bias=-1.0):
        size = self.highway_units
        X = self.current_layer

        W_T = self.call_W(str(n)+'_wt', [size,size])
        b_T = self.call_b(str(n)+'_bt', [size])
        W = self.call_W(str(n)+'_w', [size,size])
        b = self.call_b(str(n)+'_b', [size])

        T = tf.sigmoid(tf.matmul(X, W_T) + b_T, name="transform_gate")
        H = tf.nn.relu(tf.matmul(X, W) + b, name="activation")
        C = tf.subtract(1.0, T, name="carry_gate")

        Y = tf.add(tf.multiply(H, T), tf.multiply(X, C), "y") # y = (H * T) + (x * C)
        Y = tf.contrib.layers.batch_norm(Y, is_training=self.train_flag)
        self.current_layer = Y
    # end add_highway


    def add_output_layer(self):
        W = self.call_W('logits_w', [self.highway_units, self.n_out])
        b = self.call_b('logits_b', [self.n_out])
        self.logits = tf.nn.bias_add(tf.matmul(self.current_layer, W), b)
    # end method add_output_layer


    def add_backward_path(self):
        self.loss = tf.reduce_mean(tf.nn.softmax_cross_entropy_with_logits(logits=self.logits, labels=self.Y))
        self.acc = tf.reduce_mean(tf.cast(tf.equal(tf.argmax(self.logits,1),tf.argmax(self.Y,1)), tf.float32))
        # batch_norm requires update_ops
        update_ops = tf.get_collection(tf.GraphKeys.UPDATE_OPS)
        with tf.control_dependencies(update_ops):
            self.train_op = tf.train.AdamOptimizer(self.lr).minimize(self.loss)
    # end method add_backward_path


    def call_W(self, name, shape):
        return tf.get_variable(name, shape, tf.float32, tf.contrib.layers.variance_scaling_initializer())
    # end method _W


    def call_b(self, name, shape):
        return tf.get_variable(name, shape, tf.float32, tf.constant_initializer(0.01))
    # end method _b


    def fit(self, X, Y, val_data=None, n_epoch=10, batch_size=128, en_exp_decay=True, keep_prob=1.0):
        if val_data is None:
            print("Train %d samples" % len(X) )
        else:
            print("Train %d samples | Test %d samples" % (len(X), len(val_data[0])))
        log = {'loss':[], 'acc':[], 'val_loss':[], 'val_acc':[]}
        global_step = 0

        self.sess.run(tf.global_variables_initializer()) # initialize all variables
        for epoch in range(n_epoch):
            local_step = 1
            for X_batch, Y_batch in zip(self.gen_batch(X, batch_size), self.gen_batch(Y, batch_size)):
                lr = self.adjust_lr(en_exp_decay, global_step, n_epoch, len(X), batch_size)
                _, loss, acc = self.sess.run([self.train_op, self.loss, self.acc],
                                             {self.X: X_batch, self.Y: Y_batch, self.lr: lr,
                                              self.keep_prob:keep_prob, self.train_flag:True})
                local_step += 1
                global_step += 1
                if local_step % 100 == 0:
                    print ('Epoch %d/%d | Step %d/%d | train_loss: %.4f | train_acc: %.4f | lr: %.4f'
                           %(epoch+1, n_epoch, local_step, int(len(X)/batch_size), loss, acc, lr))
            if val_data is not None:
                # compute validation loss and acc
                val_loss_list, val_acc_list = [], []
                for X_test_batch, Y_test_batch in zip(self.gen_batch(val_data[0], batch_size),
                                                    self.gen_batch(val_data[1], batch_size)):
                    v_loss, v_acc = self.sess.run([self.loss, self.acc],
                                                  {self.X:X_test_batch, self.Y:Y_test_batch,
                                                   self.keep_prob:1.0, self.train_flag:False})
                    val_loss_list.append(v_loss)
                    val_acc_list.append(v_acc)
                val_loss, val_acc = self.list_avg(val_loss_list), self.list_avg(val_acc_list)

            # append to log
            log['loss'].append(loss)
            log['acc'].append(acc)
            if val_data is not None:
                log['val_loss'].append(val_loss)
                log['val_acc'].append(val_acc)

            # verbose
            if val_data is None:
                print ("Epoch %d/%d | train_loss: %.4f | train_acc: %.4f |" % (epoch+1, n_epoch, loss, acc),
                       "lr: %.4f" % (lr) )
            else:
                print ("Epoch %d/%d | train_loss: %.4f | train_acc: %.4f |" % (epoch+1, n_epoch, loss, acc),
                       "test_loss: %.4f | test_acc: %.4f |" % (val_loss, val_acc),
                       "lr: %.4f" % (lr) )
        return log
    # end method fit


    def predict(self, X_test, batch_size=128):
        batch_pred_list = []
        for X_test_batch in self.gen_batch(X_test, batch_size):
            batch_pred = self.sess.run(self.logits, {self.X:X_test_batch, self.keep_prob:1.0,
                                                     self.train_flag:False})
            batch_pred_list.append(batch_pred)
        return np.vstack(batch_pred_list)
    # end method predict


    def gen_batch(self, arr, batch_size):
        for i in range(0, len(arr), batch_size):
            yield arr[i : i+batch_size]
    # end method gen_batch


    def adjust_lr(self, en_exp_decay, global_step, n_epoch, len_X, batch_size):
        if en_exp_decay:
            max_lr = 0.003
            min_lr = 0.0001
            decay_rate = math.log(min_lr/max_lr) / (-n_epoch*len_X/batch_size)
            lr = max_lr*math.exp(-decay_rate*global_step)
        else:
            lr = 0.001
        return lr
    # end method adjust_lr


    def list_avg(self, l):
        return sum(l) / len(l)
# end class