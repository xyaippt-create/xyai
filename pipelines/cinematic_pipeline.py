from .common import add_atmosphere, apply_foundation, compress_specular, cool_shadows, tune_saturation, warm_highlights


def cinematic_tone(image):
    result = tune_saturation(image, 0.88)
    result = cool_shadows(result, 0.26)
    return warm_highlights(result, 0.12)


def depth_air(image):
    return add_atmosphere(image, 0.28)


def run(image, context):
    result = apply_foundation(image, context, include_light=True)
    result = compress_specular(result, 0.42)
    result = cinematic_tone(result)
    return depth_air(result)
