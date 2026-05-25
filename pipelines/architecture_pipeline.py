from .common import add_atmosphere, add_controlled_clarity, apply_foundation, cool_shadows


def structure_restore(image, context):
    return apply_foundation(image, context, include_light=False)


def depth_space(image):
    return add_atmosphere(image, 0.18)


def edge_volume(image):
    return add_controlled_clarity(image, 0.30, radius=1.6)


def run(image, context):
    result = structure_restore(image, context)
    result = edge_volume(result)
    result = cool_shadows(result, 0.08)
    return depth_space(result)
