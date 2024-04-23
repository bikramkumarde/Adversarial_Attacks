import os

import matplotlib.pyplot as plt
import numpy as np
import tensorflow as tf
#from tensorflow.contrib.eager.python import tfe
from tqdm import tqdm

import utils.generic_utils as generic_utils


def targetted_mse(y_generated, y_pred, target_id, alpha):
    """
    Computes the MSE between y and the target class.

    Args:
        y_generated: The predicted labels of the generated images
            from the ATN.
        y_pred: predicted matrix of size (N, C).
            N is number of samples, and C is number of classes.
        target_id: integer id of the target class.
        alpha: scaling factor for target class activations.
            Must be greater than 1.

    Returns:
        loss value
    """

    y_pred = reranking(y_pred, target_id, alpha)
    #loss = tf.losses.mean_squared_error(y_pred, y_generated, reduction=tf.losses.Reduction.NONE)
    initial_loss = tf.losses.mean_squared_error(y_pred, y_generated)
    loss = tf.reduce_mean(initial_loss)

    return loss


def reranking(y, target, alpha):
    """
    Scales the activation of the target class, then normalizes to
    a probability distribution again.

    Args:
        y: The predicted label matrix of shape [N, C]
        target: integer id for selection of target class
        alpha: scaling factor for target class activations.
            Must be greater than 1.

    Returns:

    """
    max_y = tf.reduce_max(y, axis=-1).numpy()

    weighted_y = y.numpy()  # np.ones_like(y)
    weighted_y[:, target] = alpha * max_y

    weighted_y = tf.convert_to_tensor(weighted_y)

    result = weighted_y
    result = result / tf.reduce_sum(result, axis=-1, keepdims=True)  # normalize to probability distribution

    return result


def compute_target_gradient(x, model, target):
    """
    Computes the gradient of the input image batch wrt the target output class.

    Args:
        x: batch of input of shape [B, T, C]
        model: classifier model
        target: integer id corresponding to the target class

    Returns:
        the output of the model and a list of gradients of shape [B, T, C]
    """
    with tf.GradientTape() as tape:
        tape.watch(x)  # need to watch the input tensor for grad wrt input
        out = model(x, training=False)  # in evaluation mode
        target_out = out[:, target]  # extract the target class outputs only

    input_grad = tape.gradient(target_out, x)  # compute the gradient

    return out, input_grad


def train_gatn(atn_model_fn, clf_model_fn, dataset_name, target_class_id, alpha=1.5, beta=0.01,
               epochs=1, batchsize=128, lr=1e-3,
               atn_name=None, clf_name=None, device=None):
    """
    Trains a Gradient Adversarial Transformation Network.

    Trains as a White-box attack, and accepts only Neural Neworks as its
    target classifier.

    Args:
        atn_model_fn: A callable function that returns a subclassed tf.keras Model.
             It can access the following args passed to it:
                - name: The model name, if a name is provided.
        clf_model_fn: A callable function that returns a subclassed tf.keras Model.
             It can access the following args passed to it:
                - name: The model name, if a name is provided.
        dataset_name: Name of the dataset as a string.
        target_class_id: Integer id of the target class. Ranged from [0, C-1]
            where C is the number of classes in the dataset.
        alpha: Weight of the reranking function used to compute loss Y.
        beta: Scaling weight of the reconstruction loss X.
        epochs: Number of training epochs.
        batchsize: Size of each batch.
        lr: Initial learning rate.
        atn_name: Name of the ATN model being built.
        clf_name: Name of the Classifier model being attacked.
        device: Device to place the models on.
    """
    if device is None:
        if tf.test.is_gpu_available():
            device = '/gpu:0'
        else:
            device = '/cpu:0'

    # Load the dataset
    (_, _), (X_test, y_test) = generic_utils.load_dataset(dataset_name)

    (X_train, y_train), (X_test, y_test) = generic_utils.split_dataset(X_test, y_test, test_fraction=0.5)

    num_classes = y_train.shape[-1]
    image_shape = X_train.shape[1:]

    # cleaning data
    idx = (np.argmax(y_train, axis=-1) != target_class_id)
    X_train = X_train[idx]
    y_train = y_train[idx]

    batchsize = min(batchsize, X_train.shape[0])

    num_train_batches = X_train.shape[0] // batchsize + int(X_train.shape[0] % batchsize != 0)
    num_test_batches = X_test.shape[0] // batchsize + int(X_test.shape[0] % batchsize != 0)

    # build the datasets
    train_dataset, test_dataset = generic_utils.prepare_dataset(X_train, y_train,
                                                                X_test, y_test,
                                                                batch_size=batchsize,
                                                                device=device)

    # construct the model on the correct device
    with tf.device(device):
        if clf_name is not None:
            clf_model = clf_model_fn(num_classes, name=clf_name)  # type: tf.keras.Model
        else:
            clf_model = clf_model_fn(num_classes)  # type: tf.keras.Model

        if atn_name is not None:
            atn_model = atn_model_fn(image_shape, name=atn_name)  # type: tf.keras.Model
        else:
            atn_model = atn_model_fn(image_shape)  # type: tf.keras.Model

    # Define the parameters for exponential decay
    lr_initial = 0.1  # Initial learning rate
    decay_steps = 1000  # Number of steps before decay
    decay_rate = 0.96  # Decay rate
    
    # Create an exponential decay learning rate schedule
    lr_schedule = tf.keras.optimizers.schedules.ExponentialDecay(
        initial_learning_rate=lr_initial,
        decay_steps=decay_steps,
        decay_rate=decay_rate,
        staircase=False  # Set to True if you want decay to occur at discrete intervals
    )
    # lr_schedule = tf.train.exponential_decay(lr, tf.train.get_or_create_global_step(),
    #                                          decay_steps=num_train_batches, decay_rate=0.99,
    #                                          staircase=True)
    optimizer = tf.keras.optimizers.Adam(learning_rate=lr_schedule)

    #optimizer = tf.train.AdamOptimizer(lr_schedule)

    atn_checkpoint = tf.train.Checkpoint(model=atn_model, optimizer=optimizer,
                                     global_step=tf.compat.v1.train.get_or_create_global_step())
    # lr_schedule = tf.train.exponential_decay(lr, tf.train.get_or_create_global_step(),
    #                                          decay_steps=num_train_batches, decay_rate=0.99,
    #                                          staircase=True)

    # optimizer = tf.train.AdamOptimizer(lr_schedule)

    # atn_checkpoint = tf.train.Checkpoint(model=atn_model, optimizer=optimizer,
    #                                      global_step=tf.train.get_or_create_global_step())

    clf_checkpoint = tf.train.Checkpoint(model=clf_model)

    clf_model_name = clf_model.name if clf_name is None else clf_name
    basepath = 'weights/%s/%s/' % (dataset_name, clf_model_name)

    if not os.path.exists(basepath):
        os.makedirs(basepath, exist_ok=True)

    checkpoint_path = basepath + clf_model_name

    # Restore the weights of the classifier
    clf_checkpoint.restore(checkpoint_path)

    atn_model_name = atn_model.name if atn_name is None else atn_name
    gatn_basepath = 'gatn_weights/%s/%s/' % (dataset_name, atn_model_name + "_%d" % (target_class_id))

    if not os.path.exists(gatn_basepath):
        os.makedirs(gatn_basepath, exist_ok=True)

    atn_checkpoint_path = gatn_basepath + atn_model_name + "_%d" % (target_class_id)

    best_loss = np.inf

    print()

    # train loop
    for epoch_id in range(epochs):
        train_loss = tf.keras.metrics.Mean()
        test_acc = tf.keras.metrics.Mean()
        test_target_rate = tf.keras.metrics.Mean()

        with tqdm(train_dataset,
                  desc="Epoch %d / %d: " % (epoch_id + 1, epochs),
                  total=num_train_batches, unit=' samples') as iterator:

            for train_iter, (x, y) in enumerate(iterator):
                # Train the ATN

                if train_iter >= num_train_batches:
                    break

                with tf.GradientTape() as tape:
                    y_pred, x_grad = compute_target_gradient(x, clf_model, target_class_id)
                    x_adversarial = atn_model(x, x_grad, training=True)

                    y_pred_adversarial = clf_model(x_adversarial, training=False)

                    
                    squared_difference = tf.square(x - x_adversarial)
                    loss_x = tf.reduce_mean(squared_difference)
                    
                    #loss_x = tf.losses.mean_squared_error(x, x_adversarial, reduction=tf.losses.Reduction.NONE)
                    # initial_loss = tf.losses.mean_squared_error(x, x_adversarial)
                    # loss_x = tf.reduce_mean(initial_loss)
                    
                    loss_y = targetted_mse(y_pred_adversarial, y_pred, target_class_id, alpha)
                    reshaped_loss_x = tf.reshape(loss_x, [1, 1])
                    loss_x = tf.reduce_sum(reshaped_loss_x)

                    #loss_x = tf.reduce_sum(tf.reshape(loss_x, [loss_x.shape[0], -1]), axis=-1)
                    #loss_y = tf.reduce_mean(loss_y, axis=-1)

                    loss = beta * loss_x + loss_y

                # update model weights
                gradients = tape.gradient(loss, atn_model.variables)
                grad_vars = zip(gradients, atn_model.variables)
                
                
                optimizer.apply_gradients(grad_vars)

                #optimizer.apply_gradients(grad_vars, tf.train.get_or_create_global_step())

                loss_val = tf.reduce_mean(loss)
                
                train_loss(loss_val)

        with tqdm(test_dataset, desc='Evaluating',
                  total=num_test_batches, unit=' samples') as iterator:

            for x, y in iterator:
                y_test_pred, x_test_grad = compute_target_gradient(x, clf_model, target_class_id)
                x_test_adversarial = atn_model(x, x_test_grad, training=False)

                y_pred_adversarial = clf_model(x_test_adversarial, training=False)

                # compute and update the test target_accuracy
                acc_val, target_rate = generic_utils.target_accuracy(y, y_pred_adversarial, target_class_id)

                test_acc(acc_val)
                test_target_rate(target_rate)

        print("\nEpoch %d: Train Loss = %0.5f | Test Acc = %0.6f | Target num_adv = %0.6f" % (
            epoch_id + 1, train_loss.result(), test_acc.result(), test_target_rate.result(),
        ))

        train_loss_val = train_loss.result()
        if best_loss > train_loss_val:
            print("Saving weights as training loss improved from %0.5f to %0.5f!" % (best_loss, train_loss_val))
            print()

            best_loss = train_loss_val

            atn_checkpoint.write(atn_checkpoint_path)

    print("\n\n")
    print("Finished training !")


def evaluate_gatn(atn_model_fn, clf_model_fn, dataset_name, target_class_id,
                  batchsize=128, atn_name=None, clf_name=None, device=None):
    """
    Evaluates a Gradient Adversarial Transformation Network.

    Evaluates as a White-box attack, and accepts only Neural Neworks as its
    target classifier.

    Args:
        atn_model_fn: A callable function that returns a subclassed tf.keras Model.
             It can access the following args passed to it:
                - name: The model name, if a name is provided.
        clf_model_fn: A callable function that returns a subclassed tf.keras Model.
             It can access the following args passed to it:
                - name: The model name, if a name is provided.
        dataset_name: Name of the dataset as a string.
        target_class_id: Integer id of the target class. Ranged from [0, C-1]
            where C is the number of classes in the dataset.
        batchsize: Size of each batch.
        atn_name: Name of the ATN model being built.
        clf_name: Name of the Classifier model being attacked.
        device: Device to place the models on.

    Returns:
        Does not return anything. This is only used for visual inspection.

        To obtain the scores, use the `train_scores_gatn` or
        `test_scores_gatn` functions.
    """
    if device is None:
        if tf.test.is_gpu_available():
            device = '/gpu:0'
        else:
            device = '/cpu:0'

    # Load the dataset
    (_, _), (X_test, y_test) = generic_utils.load_dataset(dataset_name)

    (X_train, y_train), (X_test, y_test) = generic_utils.split_dataset(X_test, y_test, test_fraction=0.5)

    num_classes = y_train.shape[-1]
    image_shape = X_train.shape[1:]

    # cleaning data
    # idx = (np.argmax(y_test, axis=-1) != target_class_id)
    # X_test = X_test[idx]
    # y_test = y_test[idx]

    batchsize = min(batchsize, X_train.shape[0])

    # num_train_batches = X_train.shape[0] // batchsize + int(X_train.shape[0] % batchsize != 0)
    num_test_batches = X_test.shape[0] // batchsize + int(X_test.shape[0] % batchsize != 0)

    # build the datasets
    train_dataset, test_dataset = generic_utils.prepare_dataset(X_train, y_train,
                                                                X_test, y_test,
                                                                batch_size=batchsize,
                                                                device=device)

    # construct the model on the correct device
    with tf.device(device):
        if clf_name is not None:
            clf_model = clf_model_fn(num_classes, name=clf_name)  # type: tf.keras.Model
        else:
            clf_model = clf_model_fn(num_classes)  # type: tf.keras.Model

        if atn_name is not None:
            atn_model = atn_model_fn(image_shape, name=atn_name)  # type: tf.keras.Model
        else:
            atn_model = atn_model_fn(image_shape)  # type: tf.keras.Model

    optimizer = tf.keras.optimizers.Adam()
    #optimizer = tf.train.AdamOptimizer()
    atn_checkpoint = tf.train.Checkpoint(model=atn_model, optimizer=optimizer,
                                     global_step=tf.compat.v1.train.get_or_create_global_step())
    # atn_checkpoint = tf.train.Checkpoint(model=atn_model, optimizer=optimizer,
    #                                      global_step=tf.train.get_or_create_global_step())
    #atn_checkpoint = tf.train.Checkpoint(model=atn_model)

    clf_checkpoint = tf.train.Checkpoint(model=clf_model)

    clf_model_name = clf_model.name if clf_name is None else clf_name
    basepath = 'weights/%s/%s/' % (dataset_name, clf_model_name)

    if not os.path.exists(basepath):
        os.makedirs(basepath, exist_ok=True)

    checkpoint_path = basepath + clf_model_name

    # Restore the weights of the classifier
    clf_checkpoint.restore(checkpoint_path)

    atn_model_name = atn_model.name if atn_name is None else atn_name
    gatn_basepath = 'gatn_weights/%s/%s/' % (dataset_name, atn_model_name + "_%d" % (target_class_id))

    if not os.path.exists(gatn_basepath):
        os.makedirs(gatn_basepath, exist_ok=True)

    atn_checkpoint_path = gatn_basepath + atn_model_name + "_%d" % (target_class_id)

    atn_checkpoint.restore(atn_checkpoint_path)

    # Restore the weights of the atn
    print()

    # train loop
    test_acc_whitebox = tf.keras.metrics.Mean()
    test_acc_blackbox = tf.keras.metrics.Mean()
    test_target_rate = tf.keras.metrics.Mean()
    test_mse = tf.keras.metrics.Mean()

    batch_id = 0
    adversary_ids = []

    with tqdm(test_dataset, desc='Evaluating',
              total=num_test_batches, unit=' samples') as iterator:

        for x, y in iterator:
            y_test_pred, x_test_grad = compute_target_gradient(x, clf_model, target_class_id)
            x_test_adversarial = atn_model(x, x_test_grad, training=False)

            y_pred_label = clf_model(x, training=False)
            y_pred_adversarial = clf_model(x_test_adversarial, training=False)

            # compute and update the test target_accuracy
            acc_val_white, target_rate = generic_utils.target_accuracy(y, y_pred_adversarial, target_class_id)
            acc_val_black, _ = generic_utils.target_accuracy(y_pred_label, y_pred_adversarial, target_class_id)

            #x_mse = tf.losses.mean_squared_error(x, x_test_adversarial, reduction=tf.losses.Reduction.NONE)
            initial_loss = tf.losses.mean_squared_error(x, x_test_adversarial)
            x_mse = tf.reduce_mean(initial_loss)

            test_acc_whitebox(acc_val_white)
            test_acc_blackbox(acc_val_black)
            test_target_rate(target_rate)
            test_mse(x_mse)

            # find the adversary ids
            y_labels = tf.argmax(y, axis=-1).numpy().astype(int)
            y_pred_labels = generic_utils.checked_argmax(y_test_pred, to_numpy=True).astype(int)
            y_adv_labels = generic_utils.checked_argmax(y_pred_adversarial, to_numpy=True).astype(int)

            pred_eq_ground = np.equal(y_labels, y_pred_labels)  # correct prediction
            pred_neq_adv_labels = np.not_equal(y_pred_labels,
                                               y_adv_labels)  # correct prediction was harmed by adversary

            found_adversary = np.logical_and(pred_eq_ground, pred_neq_adv_labels)

            not_same = np.argwhere(found_adversary)[:, 0]
            not_same = batch_id * batchsize + not_same
            batch_id += 1

            adversary_ids.extend(not_same.tolist())

    print("\n\nAdversary ids : ", adversary_ids)
    print(
        "\n\nTest MSE : %0.5f |  Test Acc (white box) = %0.5f | Test Acc (black box) = %0.6f | Target num_adv = %0.6f " % (
            test_mse.result(),
            test_acc_whitebox.result(), test_acc_blackbox.result(), test_target_rate.result(),))

    print("\n\n")
    print("Finished training !")


def train_scores_gatn(atn_model_fn, clf_model_fn, dataset_name, target_class_id,
                      batchsize=128, atn_name=None, clf_name=None, device=None, shuffle=True):
    """
    Evaluates a Gradient Adversarial Transformation Network and returns the metrics on
    the TRAIN SPLIT of the two splits.

    Evaluates as a White-box attack, and accepts only Neural Neworks as its
    target classifier and returns the scores of only the train set under two
    evaluation strategies :

    1) "realistic" outcome: When one is given ground truth labels to compare against.
    2) "optimistic" outcome : When we assume the classifier predictions prior to attack
                              are ground truth labels, and do not posses the real ground
                              truth labels to compare against.

    Args:
        atn_model_fn: A callable function that returns a subclassed tf.keras Model.
             It can access the following args passed to it:
                - name: The model name, if a name is provided.
        clf_model_fn: A callable function that returns a subclassed tf.keras Model.
             It can access the following args passed to it:
                - name: The model name, if a name is provided.
        dataset_name: Name of the dataset as a string.
        target_class_id: Integer id of the target class. Ranged from [0, C-1]
            where C is the number of classes in the dataset.
        batchsize: Size of each batch.
        atn_name: Name of the ATN model being built.
        clf_name: Name of the Classifier model being attacked.
        device: Device to place the models on.
        shuffle: Whether to shuffle the dataset being evaluated.

    Returns:
        (train_mse, train_acc_realistic, train_acc_optimistic, train_target_rate, adversary_ids)
    """
    if device is None:
        if tf.test.is_gpu_available():
            device = '/gpu:0'
        else:
            device = '/cpu:0'

    # Load the dataset
    (_, _), (X_test, y_test) = generic_utils.load_dataset(dataset_name)

    (X_train, y_train), (X_test, y_test) = generic_utils.split_dataset(X_test, y_test, test_fraction=0.5)

    num_classes = y_train.shape[-1]
    image_shape = X_train.shape[1:]

    # cleaning data
    # idx = (np.argmax(y_test, axis=-1) != target_class_id)
    # X_test = X_test[idx]
    # y_test = y_test[idx]

    batchsize = min(batchsize, X_train.shape[0])

    num_train_batches = X_train.shape[0] // batchsize + int(X_train.shape[0] % batchsize != 0)
    # num_test_batches = X_test.shape[0] // batchsize + int(X_test.shape[0] % batchsize != 0)

    print("Num Train Batches : ", num_train_batches)

    # build the datasets
    train_dataset, _ = generic_utils.prepare_dataset(X_train, y_train,
                                                     X_test, y_test,
                                                     batch_size=batchsize,
                                                     shuffle=shuffle,
                                                     device=device)

    # construct the model on the correct device
    with tf.device(device):
        if clf_name is not None:
            clf_model = clf_model_fn(num_classes, name=clf_name)  # type: tf.keras.Model
        else:
            clf_model = clf_model_fn(num_classes)  # type: tf.keras.Model

        if atn_name is not None:
            atn_model = atn_model_fn(image_shape, name=atn_name)  # type: tf.keras.Model
        else:
            atn_model = atn_model_fn(image_shape)  # type: tf.keras.Model

    #optimizer = tf.train.AdamOptimizer()
    optimizer = tf.keras.optimizers.Adam()
    # atn_checkpoint = tf.train.Checkpoint(model=atn_model, optimizer=optimizer,
    #                                  global_step=tf.compat.v1.train.get_or_create_global_step())

    # atn_checkpoint = tf.train.Checkpoint(model=atn_model, optimizer=optimizer,
    #                                      global_step=tf.train.get_or_create_global_step())

    atn_checkpoint = tf.train.Checkpoint(model = atn_model)

    clf_checkpoint = tf.train.Checkpoint(model=clf_model)

    clf_model_name = clf_model.name if clf_name is None else clf_name
    basepath = 'weights/%s/%s/' % (dataset_name, clf_model_name)

    if not os.path.exists(basepath):
        os.makedirs(basepath, exist_ok=True)
    checkpoint_path = basepath + clf_model_name

    # Restore the weights of the classifier
    clf_checkpoint.restore(checkpoint_path)
    atn_model_name = atn_model.name if atn_name is None else atn_name
    gatn_basepath = 'gatn_weights/%s/%s/' % (dataset_name, atn_model_name + "_%d" % (target_class_id))

    if not os.path.exists(gatn_basepath):
        os.makedirs(gatn_basepath, exist_ok=True)

    atn_checkpoint_path = gatn_basepath + atn_model_name + "_%d" % (target_class_id)

    atn_checkpoint.restore(atn_checkpoint_path)
    # Restore the weights of the atn
    print()

    # train loop
    train_acc_realistic = tf.keras.metrics.Mean()
    train_acc_optimistic = tf.keras.metrics.Mean()
    train_target_rate = tf.keras.metrics.Mean()
    train_mse = tf.keras.metrics.Mean()

    batch_id = 0
    adversary_ids = []

    with tqdm(train_dataset, desc='Evaluating',
              total=num_train_batches, unit=' samples') as iterator:

        for test_iter, (x, y) in enumerate(iterator):

            if test_iter >= num_train_batches:
                break

            y_test_pred, x_test_grad = compute_target_gradient(x, clf_model, target_class_id)
            x_test_adversarial = atn_model(x, x_test_grad, training=False)

            y_test_pred = clf_model(x, training=False)
            y_pred_adversarial = clf_model(x_test_adversarial, training=False)

            # compute and update the test target_accuracy
            acc_val_white, target_rate = generic_utils.target_accuracy(y, y_pred_adversarial, target_class_id)
            acc_val_black, _ = generic_utils.target_accuracy(y_test_pred, y_pred_adversarial, target_class_id)

            initial_loss = tf.losses.mean_squared_error(x, x_test_adversarial)
            x_mse = tf.reduce_mean(initial_loss)
            #x_mse = tf.losses.mean_squared_error(x, x_test_adversarial, reduction=tf.losses.Reduction.NONE)

            train_acc_realistic(acc_val_white)
            train_acc_optimistic(acc_val_black)
            train_target_rate(target_rate)
            train_mse(x_mse)

            # find the adversary ids
            y_labels = tf.argmax(y, axis=-1).numpy().astype(int)
            y_pred_labels = generic_utils.checked_argmax(y_test_pred, to_numpy=True).astype(int)
            y_adv_labels = generic_utils.checked_argmax(y_pred_adversarial, to_numpy=True).astype(
                int)  # tf.argmax(y_pred_adversarial, axis=-1)

            pred_eq_ground = np.equal(y_labels, y_pred_labels)  # correct prediction
            pred_neq_adv_labels = np.not_equal(y_pred_labels,
                                               y_adv_labels)  # correct prediction was harmed by adversary

            found_adversary = np.logical_and(pred_eq_ground, pred_neq_adv_labels)

            not_same = np.argwhere(found_adversary)[:, 0]
            not_same = batch_id * batchsize + not_same
            batch_id += 1

            adversary_ids.extend(not_same.tolist())

    return (train_mse.result().numpy(),
            train_acc_realistic.result().numpy(), train_acc_optimistic.result().numpy(),
            train_target_rate.result().numpy(), adversary_ids)


def test_scores_gatn(atn_model_fn, clf_model_fn, dataset_name, target_class_id,
                     batchsize=128, atn_name=None, clf_name=None, device=None, shuffle=True):
    """
    Evaluates a Gradient Adversarial Transformation Network and returns the metrics on
    the unseen TEST SPLIT of the two splits.

    Evaluates as a White-box attack, and accepts only Neural Neworks as its
    target classifier and returns the scores of only the train set under two
    evaluation strategies :

    1) "realistic" outcome: When one is given ground truth labels to compare against.
    2) "optimistic" outcome : When we assume the classifier predictions prior to attack
                              are ground truth labels, and do not posses the real ground
                              truth labels to compare against.

    Args:
        atn_model_fn: A callable function that returns a subclassed tf.keras Model.
             It can access the following args passed to it:
                - name: The model name, if a name is provided.
        clf_model_fn: A callable function that returns a subclassed tf.keras Model.
             It can access the following args passed to it:
                - name: The model name, if a name is provided.
        dataset_name: Name of the dataset as a string.
        target_class_id: Integer id of the target class. Ranged from [0, C-1]
            where C is the number of classes in the dataset.
        batchsize: Size of each batch.
        atn_name: Name of the ATN model being built.
        clf_name: Name of the Classifier model being attacked.
        device: Device to place the models on.
        shuffle: Whether to shuffle the dataset being evaluated.

    Returns:
        (test_mse, test_acc_realistic, test_acc_optimistic, test_target_rate, adversary_ids)
    """
    if device is None:
        if tf.test.is_gpu_available():
            device = '/gpu:0'
        else:
            device = '/cpu:0'

    # Load the dataset
    (_, _), (X_test, y_test) = generic_utils.load_dataset(dataset_name)

    (X_train, y_train), (X_test, y_test) = generic_utils.split_dataset(X_test, y_test, test_fraction=0.5)

    num_classes = y_train.shape[-1]
    image_shape = X_train.shape[1:]

    # cleaning data
    # idx = (np.argmax(y_test, axis=-1) != target_class_id)
    # X_test = X_test[idx]
    # y_test = y_test[idx]

    batchsize = min(batchsize, X_train.shape[0])

    # num_train_batches = X_train.shape[0] // batchsize + int(X_train.shape[0] % batchsize != 0)
    num_test_batches = X_test.shape[0] // batchsize + int(X_test.shape[0] % batchsize != 0)

    print("Num Test Batches : ", num_test_batches)

    # build the datasets
    _, test_dataset = generic_utils.prepare_dataset(X_train, y_train,
                                                    X_test, y_test,
                                                    batch_size=batchsize,
                                                    shuffle=shuffle,
                                                    device=device)

    # construct the model on the correct device
    with tf.device(device):
        if clf_name is not None:
            clf_model = clf_model_fn(num_classes, name=clf_name)  # type: tf.keras.Model
        else:
            clf_model = clf_model_fn(num_classes)  # type: tf.keras.Model

        if atn_name is not None:
            atn_model = atn_model_fn(image_shape, name=atn_name)  # type: tf.keras.Model
        else:
            atn_model = atn_model_fn(image_shape)  # type: tf.keras.Model

    optimizer = tf.keras.optimizers.Adam()
    #optimizer = tf.train.AdamOptimizer()

    # atn_checkpoint = tf.train.Checkpoint(model=atn_model, optimizer=optimizer,
    #                                  global_step=tf.compat.v1.train.get_or_create_global_step())
    # atn_checkpoint = tf.train.Checkpoint(model=atn_model, optimizer=optimizer,
    #                                      global_step=tf.train.get_or_create_global_step())

    atn_checkpoint = tf.train.Checkpoint(model=atn_model)
    clf_checkpoint = tf.train.Checkpoint(model=clf_model)

    clf_model_name = clf_model.name if clf_name is None else clf_name
    basepath = 'weights/%s/%s/' % (dataset_name, clf_model_name)

    if not os.path.exists(basepath):
        os.makedirs(basepath, exist_ok=True)

    checkpoint_path = basepath + clf_model_name

    # Restore the weights of the classifier
    clf_checkpoint.restore(checkpoint_path)

    atn_model_name = atn_model.name if atn_name is None else atn_name
    gatn_basepath = 'gatn_weights/%s/%s/' % (dataset_name, atn_model_name + "_%d" % (target_class_id))

    if not os.path.exists(gatn_basepath):
        os.makedirs(gatn_basepath, exist_ok=True)

    atn_checkpoint_path = gatn_basepath + atn_model_name + "_%d" % (target_class_id)

    atn_checkpoint.restore(atn_checkpoint_path)

    # Restore the weights of the atn
    print()

    # train loop
    test_acc_realistic = tf.keras.metrics.Mean()
    test_acc_optimistic = tf.keras.metrics.Mean()
    test_target_rate = tf.keras.metrics.Mean()
    test_mse = tf.keras.metrics.Mean()

    batch_id = 0
    adversary_ids = []

    with tqdm(test_dataset, desc='Evaluating',
              total=num_test_batches, unit=' samples') as iterator:

        for test_iter, (x, y) in enumerate(iterator):

            if test_iter >= num_test_batches:
                break

            y_test_pred, x_test_grad = compute_target_gradient(x, clf_model, target_class_id)
            x_test_adversarial = atn_model(x, x_test_grad, training=False)

            y_test_pred = clf_model(x, training=False)
            y_pred_adversarial = clf_model(x_test_adversarial, training=False)

            # compute and update the test target_accuracy
            acc_val_white, target_rate = generic_utils.target_accuracy(y, y_pred_adversarial, target_class_id)
            acc_val_black, _ = generic_utils.target_accuracy(y_test_pred, y_pred_adversarial, target_class_id)

            #x_mse = tf.losses.mean_squared_error(x, x_test_adversarial, reduction=tf.losses.Reduction.NONE)
            initial_loss = tf.losses.mean_squared_error(x, x_test_adversarial)
            x_mse = tf.reduce_mean(initial_loss)

            test_acc_realistic(acc_val_white)
            test_acc_optimistic(acc_val_black)
            test_target_rate(target_rate)
            test_mse(x_mse)

            # find the adversary ids
            y_labels = tf.argmax(y, axis=-1).numpy().astype(int)
            y_pred_labels = generic_utils.checked_argmax(y_test_pred, to_numpy=True).astype(int)
            y_adv_labels = generic_utils.checked_argmax(y_pred_adversarial, to_numpy=True).astype(
                int)  # tf.argmax(y_pred_adversarial, axis=-1)

            pred_eq_ground = np.equal(y_labels, y_pred_labels)  # correct prediction
            pred_neq_adv_labels = np.not_equal(y_pred_labels,
                                               y_adv_labels)  # correct prediction was harmed by adversary

            found_adversary = np.logical_and(pred_eq_ground, pred_neq_adv_labels)

            not_same = np.argwhere(found_adversary)[:, 0]
            not_same = batch_id * batchsize + not_same
            batch_id += 1

            adversary_ids.extend(not_same.tolist())

    return (test_mse.result().numpy(), test_acc_realistic.result().numpy(), test_acc_optimistic.result().numpy(),
            test_target_rate.result().numpy(), adversary_ids)


def visualise_gatn(atn_model_fn, clf_model_fn, dataset_name, target_class_id, class_id=0, sample_id=0,
                   plot_delta=False, atn_name=None, clf_name=None, device=None, dataset_type='train',
                   save_image=False):
    """
    Visualize the generated white-box adversarial samples.

    Args:
        atn_model_fn: A callable function that returns a subclassed tf.keras Model.
             It can access the following args passed to it:
                - name: The model name, if a name is provided.
        clf_model_fn: A callable function that returns a subclassed tf.keras Model.
             It can access the following args passed to it:
                - name: The model name, if a name is provided.
        dataset_name: Name of the dataset as a string.
        target_class_id: Integer id of the target class. Ranged from [0, C-1]
            where C is the number of classes in the dataset.
        class_id: Integer class id or None for random sample from any class.
        sample_id: Integer sample id or None for random sample from entire dataset.
        plot_delta: Whether to plot just the adversarial sample, or both the original
            and the adversarial to visually inspect the delta between the two.
        atn_name: Name of the ATN model being built.
        clf_name: Name of the Classifier model being attacked.
        device: Device to place the models on.
        dataset_type: Can be "train" or "test". Decides whether to sample from
            the GATN training or testing set.
        save_image: Bool whether to save the image to file instead of plotting it.
    """
    np.random.seed(0)

    if device is None:
        if tf.test.is_gpu_available():
            device = '/gpu:0'
        else:
            device = '/cpu:0'

    if dataset_type not in ['train', 'test']:
        raise ValueError("Dataset type must be 'train' or 'test'")

    # Load the dataset
    (X_train, y_train), (X_test, y_test) = generic_utils.load_dataset(dataset_name)

    num_classes = y_train.shape[-1]
    image_shape = X_train.shape[1:]

    # cleaning data
    if class_id is not None:
        assert class_id in np.unique(np.argmax(y_test, axis=-1)), "Class id must be part of the labels of the dataset !"

    # construct the model on the correct device
    with tf.device(device):
        if clf_name is not None:
            clf_model = clf_model_fn(num_classes, name=clf_name)  # type: tf.keras.Model
        else:
            clf_model = clf_model_fn(num_classes)  # type: tf.keras.Model

        if atn_name is not None:
            atn_model = atn_model_fn(image_shape, name=atn_name)  # type: tf.keras.Model
        else:
            atn_model = atn_model_fn(image_shape)  # type: tf.keras.Model

    optimizer = tf.keras.optimizers.Adam()
    #optimizer = tf.train.AdamOptimizer()
    # atn_checkpoint = tf.train.Checkpoint(model=atn_model, optimizer=optimizer,
    #                                  global_step=tf.compat.v1.train.get_or_create_global_step())
    

    atn_checkpoint = tf.train.Checkpoint(model=atn_model)
    clf_checkpoint = tf.train.Checkpoint(model=clf_model)

    clf_model_name = clf_model.name if clf_name is None else clf_name
    basepath = 'weights/%s/%s/' % (dataset_name, clf_model_name)

    if not os.path.exists(basepath):
        os.makedirs(basepath, exist_ok=True)

    checkpoint_path = basepath + clf_model_name

    # Restore the weights of the classifier
    clf_checkpoint.restore(checkpoint_path)

    atn_model_name = atn_model.name if atn_name is None else atn_name
    gatn_basepath = 'gatn_weights/%s/%s/' % (dataset_name, atn_model_name + "_%d" % (target_class_id))

    if not os.path.exists(gatn_basepath):
        os.makedirs(gatn_basepath, exist_ok=True)

    atn_checkpoint_path = gatn_basepath + atn_model_name + "_%d" % (target_class_id)

    atn_checkpoint.restore(atn_checkpoint_path)

    # Restore the weights of the atn
    print()

    sample_idx = sample_id  # np.random.randint(0, len(X_test))

    if class_id is None:

        if dataset_type == 'train':
            x = X_train[[sample_idx]]
            y = np.argmax(y_train[sample_idx])

        else:
            x = X_test[[sample_idx]]
            y = np.argmax(y_test[sample_idx])

    else:
        if dataset_type == 'train':
            class_indices = (np.argmax(y_train, axis=-1) == class_id)
            print("Number of samples of class %d = %d" % (class_id, np.sum(class_indices)))

            x = X_train[class_indices][[sample_idx]]
            y = np.argmax(y_train[class_indices][sample_idx])

        else:
            class_indices = (np.argmax(y_test, axis=-1) == class_id)
            print("Number of samples of class %d = %d" % (class_id, np.sum(class_indices)))

            x = X_test[class_indices][[sample_idx]]
            y = np.argmax(y_test[class_indices][sample_idx])

    x = tf.convert_to_tensor(x)

    y_pred_label, x_test_grad = compute_target_gradient(x, clf_model, target_class_id)
    x_test_adversarial = atn_model(x, x_test_grad, training=False)

    y_pred_adversarial = clf_model(x_test_adversarial, training=False)
    y_pred_adversarial_label = generic_utils.checked_argmax(y_pred_adversarial)[
        0]  # tf.argmax(y_pred_adversarial[0], axis=-1)

    y_pred_class = generic_utils.checked_argmax(y_pred_label, to_numpy=True)[0]  # np.argmax(y_pred_label)
    y_pred_proba = y_pred_label[0, y_pred_class]
    y_adversarial_pred_proba = y_pred_adversarial[0, y_pred_adversarial_label]

    mse_loss = tf.losses.mean_squared_error(x, x_test_adversarial)

    print("Ground truth : ", y)
    print("Real predicted probability (class = %d) : %0.5f" % (y_pred_class, y_pred_proba))
    print(
        "Adverarial predicted probability (class = %d) : %0.5f" % (y_pred_adversarial_label, y_adversarial_pred_proba))
    mse_scalar = tf.reduce_mean(mse_loss).numpy()
    print("Mean Squared error between X and X adversarial' : %0.6f" % (mse_scalar))

    if plot_delta:
        fig, axes = plt.subplots(1, 1, sharex=True, squeeze=True)

        generic_utils.plot_image_adversary(x.numpy(), y, axes, imlabel='Real X')
        generic_utils.plot_image_adversary(x_test_adversarial.numpy(),
                                           "Adversarial label : " + str(y_pred_adversarial_label.numpy()) + (
                                                ' - Real label : ' + str(y)
                                           ),
                                           axes, remove_axisgrid=False,
                                           xlabel='Timesteps', ylabel='Magnitude',
                                           legend=True, imlabel='Adversarial X')

    else:
        fig, axes = plt.subplots(1, 2, sharex=True, squeeze=True)

        generic_utils.plot_image_adversary(x.numpy(), y, axes[0], imlabel='Real X')
        generic_utils.plot_image_adversary(x_test_adversarial.numpy(),
                                           "Adversarial label : " + str(y_pred_adversarial_label.numpy()) + (
                                                 ' - Real label : ' + str(y)
                                           ),
                                           axes[1],
                                           xlabel='Timesteps', ylabel='Magnitude',
                                           legend=True, imlabel='Adversarial X')
    if not save_image:
        plt.show()
    else:
        if not os.path.exists('images/'):
            os.makedirs('images/')

        dataset_id = int(dataset_name[4:])
        if sample_id is None:
            sample_id = -1

        filename = 'images/whitebox-dataset-%d-sample-%d.png' % (dataset_id, sample_id)
        plt.savefig(filename)
