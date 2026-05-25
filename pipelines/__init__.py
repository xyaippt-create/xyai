from .ai_commercial_kv_pipeline import run as run_ai_commercial_kv
from .architecture_pipeline import run as run_architecture
from .cinematic_pipeline import run as run_cinematic
from .cosmetics_pipeline import run as run_cosmetics
from .food_pipeline import run as run_food
from .luxury_product_pipeline import run as run_luxury_product
from .portrait_pipeline import run as run_portrait
from .ppt_business_pipeline import run as run_ppt_business
from .common import PipelineContext


PIPELINE_REGISTRY = {
    "ai_commercial_kv": run_ai_commercial_kv,
    "architecture": run_architecture,
    "cinematic": run_cinematic,
    "cosmetics": run_cosmetics,
    "food": run_food,
    "luxury_product": run_luxury_product,
    "portrait_commercial": run_portrait,
    "ppt_business": run_ppt_business,
}


def run_mode_pipeline(mode_name: str, image, context: PipelineContext):
    pipeline = PIPELINE_REGISTRY.get(mode_name, run_ai_commercial_kv)
    return pipeline(image, context)


__all__ = ["PipelineContext", "PIPELINE_REGISTRY", "run_mode_pipeline"]
