from .common import add_controlled_clarity, apply_foundation, compress_specular, cool_shadows, soft_glow


def metal_reflection(image):
    return add_controlled_clarity(image, 0.34, radius=2.2)


def commercial_specular(image):
    return compress_specular(image, 0.46)


def glass_material(image):
    result = cool_shadows(image, 0.22)
    return soft_glow(result, 0.08, sigma=0.9)


def run(image, context):
    result = apply_foundation(image, context, include_light=False)
    result = metal_reflection(result)
    result = commercial_specular(result)
    return glass_material(result)
