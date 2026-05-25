from .common import add_atmosphere, add_controlled_clarity, apply_foundation, compress_specular, soft_glow


def subject_control(image):
    return add_controlled_clarity(image, 0.20, radius=1.8)


def premium_kv_air(image):
    result = compress_specular(image, 0.34)
    result = soft_glow(result, 0.12, sigma=1.1)
    return add_atmosphere(result, 0.18)


def run(image, context):
    result = apply_foundation(image, context, include_light=True)
    result = subject_control(result)
    return premium_kv_air(result)
