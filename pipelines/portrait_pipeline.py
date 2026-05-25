from .common import add_atmosphere, apply_foundation, compress_specular, soft_glow, tune_saturation


def skin_frequency(image, context):
    return apply_foundation(image, context, include_light=True)


def skin_soft_light(image):
    return soft_glow(image, 0.34, sigma=1.6)


def beauty_glow(image):
    result = compress_specular(image, 0.40)
    result = tune_saturation(result, 0.94)
    return add_atmosphere(result, 0.16)


def run(image, context):
    result = skin_frequency(image, context)
    result = skin_soft_light(result)
    return beauty_glow(result)
