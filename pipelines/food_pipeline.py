from .common import add_atmosphere, apply_foundation, soft_glow, tune_saturation, warm_highlights


def food_texture(image, context):
    return apply_foundation(image, context, include_light=False)


def food_gloss(image):
    return warm_highlights(soft_glow(image, 0.16, sigma=1.0), 0.34)


def steam_air(image):
    return add_atmosphere(image, 0.16)


def run(image, context):
    result = food_texture(image, context)
    result = tune_saturation(result, 1.08)
    result = food_gloss(result)
    return steam_air(result)
