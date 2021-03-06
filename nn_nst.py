import numpy as np
import matplotlib.pyplot as plt
import tensorflow as tf
from tensorflow import keras
from PIL import Image

img = Image.open('gorod.jpg')
img_style = Image.open('zvezdnoe_nebo2.jpeg')

# В данном примере используется НС VGG19, поэтому необходимо привести картинку из формата RGB в формат BGR

x_img = keras.applications.vgg19.preprocess_input(np.expand_dims(img, axis=0))
x_style = keras.applications.vgg19.preprocess_input(np.expand_dims(img_style, axis=0))

def deprocess_img(processed_img):
    """
    Функция, которая преобразует картинку из формата BGR в формат RGB
    """
    x = processed_img.copy()
    if len(x.shape) == 4:
        x = np.squeeze(x, 0)
    assert len(x.shape) == 3, ("Input to deprocess image  must be an image of"
                               "dimension [1, height, width, channel] or"
                               "[height, width, channel]")

    if len(x.shape) != 3:
        raise ValueError("Invalid input to deprocessing image")

    # perform the inverse of the preprocessing step
    x[:, :, 0] += 103.939
    x[:, :, 1] += 116.779
    x[:, :, 2] += 123.68
    x = x[:, :, ::-1] # меняем местами

    x = np.clip(x, 0, 255).astype('uint8') # отбрасывем все, что меньше нуля и больше 255
    return x

# Content layer where will pull our feature map
content_layers = ['block5_conv2']

# Style layer we are intrested in
# Названия этих слоев взяты исходя из названий слоев в VGG19
style_layers = ['block1_conv1',
                'block2_conv1',
                'block3_conv1',
                'block4_conv1',
                'block5_conv1'
                ]

num_content_layers = len(content_layers)
num_style_layers = len(style_layers)

# Загружаем НС VGG19

vgg = keras.applications.vgg19.VGG19(include_top=False, weights="imagenet")

# Чтобы сеть не меняла веса и не обучалась вводим параметр
vgg.trainable = False

# Определяем выходы нейронной сети и строим модель

style_outputs = [vgg.get_layer(name).output for name in style_layers]
content_outputs = [vgg.get_layer(name).output for name in content_layers]
model_outputs = style_outputs + content_outputs

print(vgg.input)
for m in model_outputs:
    print(m)

model = keras.models.Model(vgg.input, model_outputs)
print(model.summary()) # вывод структуры НС в консоль


def get_content_loss(base_content, target):
    """ Функция, которая вычисляет потери по контенту"""
    return tf.reduce_mean(tf.square(base_content - target))


"""Вспомогательные функции для расчета потерь по стилю"""
def gram_matrix(input_tensor):
    """Вычисляет матрице Грама для переданного тензора input_tensor"""
    # We make the image channels first
    channels = int(input_tensor.shape[-1])
    a = tf.reshape(input_tensor, [-1, channels])
    n = tf.shape(a)[0]
    gram = tf.matmul(a, a, transpose_a=True)
    return gram/tf.cast(n, tf.float32)

def get_style_loss(base_style, gram_target):
    """Функция, которая определяет рассогласование двух изображений для опеределенного слоя сети
        вычисления производятся за счет разности матриц Грама формируемого изображения и стилизованного изображения
    """
    # height, width, num filters of each layer
    # We scale the loss at given layer by the size of the feature map and the number filters
    height, width, channels = base_style.get_shape().as_list()
    gram_style = gram_matrix(base_style)

    return tf.reduce_mean(tf.square(gram_style-gram_target)) # / (4. * (channels ** 2) * (width * height) ** 2)

def get_feature_representations(model):
    # batch compute content and style
    style_outputs = model(x_style)
    content_outputs = model(x_img)

    # Get the style and content feature representations from our model
    style_features = [style_layer[0] for style_layer in style_outputs[:num_style_layers]]
    content_features = [content_layer[0] for content_layer in content_outputs[num_style_layers:]]
    return style_features, content_features

def compute_loss(model, loss_weights, init_image, gram_style_features, content_features):
    """Функция для вычисления оьщих потерь"""
    style_weight, content_weight = loss_weights #альфа и бетта коэфициенты

    model_outputs = model(init_image) # Пропускаем модель через НС и на выходе получаем значения на каждом нужном сверточном слое


    # Получаем карты признаков для стиля и контента
    style_outputs_features = model_outputs[:num_style_layers]
    content_output_features = model_outputs[num_style_layers:]

    # Введем переменные в которых будем хранить величины для стиля и контента
    style_score = 0
    content_score = 0

    #Accumulate style losses from all layers
    #Here, we equally weight each contribution of each loss layer
    weight_per_style_layer = 1.0 / float(num_content_layers)
    for target_style, comb_style in zip(gram_style_features, style_outputs_features):
        style_score += weight_per_style_layer * get_style_loss(comb_style[0], target_style)


    #Accumulate content losses from all  layers
    weight_per_content_layer = 1 / float(num_content_layers)
    for target_content, comb_content in zip(content_features, content_output_features):
        content_score += weight_per_content_layer * get_content_loss(comb_content[0], target_content)

    style_score *= style_weight
    content_score *= content_weight

    # Get total loss
    loss = style_score + content_score
    return loss, style_score, content_score



num_iterations=100
content_weight=1e3 # Пареметр альфа (насколько важен контент)
style_weight=1e-2 # Параметр бетта на сколько стилизован рисунок


# Пропускаем через НС два изображения (формируемое и стилевое)
style_features, content_features = get_feature_representations(model)
# Вычисляем матрицу Грама для картинки со стилями
gram_style_features = [gram_matrix(style_feature) for style_feature in style_features]



init_image = np.copy(x_img) #Начальное изображение
init_image = tf.Variable(init_image, dtype=tf.float32) #Преобразовываем картинку в вид, понимаемый Tensorflow

# Создаем оптимизаторы для алгоритма градиентного спуска
opt = tf.compat.v1.train.AdamOptimizer(learning_rate=2, beta1=0.99, epsilon=1e-1)
iter_count = 1
# Лучшие потери, лучшие изображения соотыетствующие лучшим потерям
best_loss, best_img = float('inf'), None
# Веса бетта и альфа
loss_weights = (style_weight, content_weight)

# Для удобства все записываем в словарь
cfg = {
    'model': model,
    'loss_weights': loss_weights,
    'init_image': init_image,
    'gram_style_features': gram_style_features,
    'content_features': content_features
}

# Преобразовываем параметры изображения из BGR в RGB
norm_means = np.array([103.939, 116.779, 123.68])
min_vals = -norm_means
max_vals = 255 - norm_means
imgs = [] # Переменная будет содержать все изображения, которые мы сформируем в процессе работы

# Запуск алгоритма градиентного спуска
for i in range(num_iterations):
    with tf.GradientTape() as tape:
        all_loss = compute_loss(**cfg)

    loss, style_score, content_score = all_loss
    grads = tape.gradient(loss, init_image)

    opt.apply_gradients([(grads, init_image)])
    clipped = tf.clip_by_value(init_image, min_vals, max_vals)
    init_image.assign(clipped)

    if loss < best_loss:
        # Update best loss and best image from total loss.
        best_loss = loss
        best_img = deprocess_img(init_image.numpy())

        # Use the .numpy() method to get the concrete numpy array
        plot_img = deprocess_img(init_image.numpy())
        imgs.append(plot_img)
        print('Iteration: {}'.format(i))

plt.imshow(best_img)
print(best_loss)

image = Image.fromarray(best_img.astype('uint8'), 'RGB')
image.save("result3.jpg")




















