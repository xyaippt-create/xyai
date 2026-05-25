from .common import add_atmosphere, apply_foundation, compress_specular, soft_glow, tune_saturation


def skin_soft_light(image):
    return soft_glow(image, 0.28, sigma=1.4)


def beauty_glow(image):
    result = compress_specular(image, 0.36)
    return add_atmosphere(result, 0.10)


def skin_frequency(image, context):
    result = apply_foundation(image, context, include_light=True)
    return tune_saturation(result, 0.96)


def run(image, context):
    result = skin_frequency(image, context)
    result = skin_soft_light(result)
    return beauty_glow(result)
