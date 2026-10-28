"""Shared final-output policies for HDDE product images."""

from .filename_policy import (
    FEATURE_1080P,
    FEATURE_4K,
    FEATURE_COLOR,
    FEATURE_COMPRESSION,
    FEATURE_RETOUCH,
    FEATURE_WATERMARK,
    build_output_filename,
    build_output_path,
    resolve_collision_path,
)
from .metadata_writer import (
    HDDE_COMMENT,
    HDDE_KEYWORDS,
    HDDE_SOFTWARE,
    read_hdde_metadata,
    write_hdde_metadata,
    write_hdde_metadata_bytes,
)
from .publish_safety import (
    PRIVATE_OUTPUT_PREFIX,
    PRIVATE_OUTPUT_SUFFIX,
    OutputMetadataStageError,
    publish_image_bytes_with_metadata,
    publish_image_file_with_metadata,
    publish_prepared_bytes_no_overwrite,
)

__all__ = [
    "FEATURE_1080P",
    "FEATURE_4K",
    "FEATURE_COLOR",
    "FEATURE_COMPRESSION",
    "FEATURE_RETOUCH",
    "FEATURE_WATERMARK",
    "HDDE_COMMENT",
    "HDDE_KEYWORDS",
    "HDDE_SOFTWARE",
    "PRIVATE_OUTPUT_PREFIX",
    "PRIVATE_OUTPUT_SUFFIX",
    "OutputMetadataStageError",
    "build_output_filename",
    "build_output_path",
    "read_hdde_metadata",
    "resolve_collision_path",
    "write_hdde_metadata",
    "write_hdde_metadata_bytes",
    "publish_image_bytes_with_metadata",
    "publish_image_file_with_metadata",
    "publish_prepared_bytes_no_overwrite",
]
