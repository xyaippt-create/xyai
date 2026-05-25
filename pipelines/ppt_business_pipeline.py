from .common import add_controlled_clarity, apply_foundation, compress_specular, protect_text_edges, tune_saturation


def layout_clean_background(image):
    result = compress_specular(image, 0.22)
    return tune_saturation(result, 0.98)


def text_protection(image):
    return protect_text_edges(image, 0.68)


def run(image, context):
    result = apply_foundation(image, context, include_light=True)
    result = layout_clean_background(result)
    result = add_controlled_clarity(result, 0.14, radius=1.2)
    return text_protection(result)
