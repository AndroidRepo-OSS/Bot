from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

_ARTWORK_FORMATS = ("JPEG", "PNG", "WEBP", "TIFF")
_MAX_SOURCE_PIXELS = 40_000_000


class ArtworkDecodeError(ValueError):
    pass


def decode_artwork(content: bytes) -> Image.Image:
    try:
        return _decode_artwork(content)
    except ArtworkDecodeError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning, OSError, UnidentifiedImageError) as error:
        msg = "Banner source image is not a safe supported image"
        raise ArtworkDecodeError(msg) from error


def _decode_artwork(content: bytes) -> Image.Image:
    with Image.open(BytesIO(content), formats=_ARTWORK_FORMATS) as source:
        _enforce_pixel_limit(source)
        source.load()
        transposed = ImageOps.exif_transpose(source)
        try:
            return transposed.convert("RGB")
        finally:
            transposed.close()


def _enforce_pixel_limit(image: Image.Image) -> None:
    if image.width * image.height <= _MAX_SOURCE_PIXELS:
        return
    msg = "Banner source image exceeds the pixel limit"
    raise ArtworkDecodeError(msg)


def decode_png_asset(content: bytes) -> Image.Image:
    with Image.open(BytesIO(content), formats=("PNG",)) as source:
        source.load()
        return source.convert("RGBA")
