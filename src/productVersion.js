import productVersion from "../product_version.json";

export const PRODUCT_VERSION = productVersion.version;
export const PRODUCT_VERSION_LABEL = productVersion.display_version;
export const PRODUCT_RELEASE_NAME = productVersion.release_name;
export const PRODUCT_RELEASE_CHANNEL = productVersion.release_channel;
export const PRODUCT_BRAND_LINE = `影界 HDDE ${PRODUCT_VERSION_LABEL} · HD Delivery Engine · 中文视觉高清交付引擎`;

export default Object.freeze({
  version: PRODUCT_VERSION,
  displayVersion: PRODUCT_VERSION_LABEL,
  releaseName: PRODUCT_RELEASE_NAME,
  releaseChannel: PRODUCT_RELEASE_CHANNEL,
});
