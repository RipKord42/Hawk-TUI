# =============================================================================
# Terminal Image Rendering
# =============================================================================
# Converts images to terminal-displayable formats.
#
# Supported protocols:
#   - Sixel: Bitmap graphics protocol, supported by xterm, mlterm, etc.
#   - Kitty: Modern protocol with better quality, requires Kitty terminal
#
# The process:
#   1. Load image (from attachment data or URL)
#   2. Resize to fit terminal dimensions
#   3. Convert to appropriate protocol format
#   4. Return data ready for terminal output
# =============================================================================

from dataclasses import dataclass
from io import BytesIO
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL import Image


@dataclass
class ImageDimensions:
    """
    Dimensions for image display.

    Attributes:
        width: Width in terminal cells.
        height: Height in terminal rows.
        pixel_width: Actual pixel width.
        pixel_height: Actual pixel height.
    """
    width: int          # Terminal cells
    height: int         # Terminal rows
    pixel_width: int    # Actual pixels
    pixel_height: int   # Actual pixels


class ImageRenderer:
    """
    Renders images for terminal display.

    Handles resizing and conversion to terminal graphics protocols.

    Usage:
        >>> renderer = ImageRenderer(max_width=80, max_height=40)
        >>> sixel_data = renderer.render_sixel(image_bytes)
        >>> kitty_data = renderer.render_kitty(image_bytes)
    """

    def __init__(
        self,
        max_width: int = 80,
        max_height: int = 40,
        cell_width: int = 8,
        cell_height: int = 16,
    ) -> None:
        """
        Initialize the image renderer.

        Args:
            max_width: Maximum width in terminal cells.
            max_height: Maximum height in terminal rows.
            cell_width: Pixel width of a terminal cell.
            cell_height: Pixel height of a terminal cell.
        """
        self.max_width = max_width
        self.max_height = max_height
        self.cell_width = cell_width
        self.cell_height = cell_height

    def load_image(self, data: bytes) -> "Image.Image":
        """
        Load an image from bytes.

        Args:
            data: Image data (PNG, JPEG, GIF, etc.)

        Returns:
            PIL Image object.
        """
        from PIL import Image
        return Image.open(BytesIO(data))

    def resize_image(
        self,
        image: "Image.Image",
        max_width: int | None = None,
        max_height: int | None = None,
    ) -> tuple["Image.Image", ImageDimensions]:
        """
        Resize image to fit terminal constraints.

        Maintains aspect ratio while fitting within max dimensions.

        Args:
            image: PIL Image to resize.
            max_width: Max width in cells (uses self.max_width if None).
            max_height: Max height in rows (uses self.max_height if None).

        Returns:
            Tuple of (resized image, dimensions).
        """
        max_w = (max_width or self.max_width) * self.cell_width
        max_h = (max_height or self.max_height) * self.cell_height

        # Calculate new size maintaining aspect ratio
        width, height = image.size
        ratio = min(max_w / width, max_h / height)

        if ratio < 1:
            new_width = int(width * ratio)
            new_height = int(height * ratio)
            image = image.resize((new_width, new_height))
        else:
            new_width, new_height = width, height

        # Calculate terminal dimensions
        cell_width = (new_width + self.cell_width - 1) // self.cell_width
        cell_height = (new_height + self.cell_height - 1) // self.cell_height

        dims = ImageDimensions(
            width=cell_width,
            height=cell_height,
            pixel_width=new_width,
            pixel_height=new_height,
        )

        return image, dims

    def render_sixel(self, data: bytes) -> tuple[bytes, ImageDimensions]:
        """
        Render image as Sixel graphics.

        Sixel is a bitmap graphics format supported by many terminals.
        Each sixel represents a 1x6 pixel column.

        Args:
            data: Image data (PNG, JPEG, etc.)

        Returns:
            Tuple of (sixel data, dimensions).
        """
        # TODO: Implement Sixel encoding
        # Options:
        # 1. Use libsixel via ctypes
        # 2. Pure Python implementation
        # 3. Shell out to img2sixel
        raise NotImplementedError("Sixel rendering not yet implemented")

    def render_kitty(
        self,
        data: bytes,
        max_width: int | None = None,
        max_height: int | None = None,
    ) -> tuple[str, ImageDimensions]:
        """
        Render image using Kitty graphics protocol.

        The Kitty protocol transmits images as base64-encoded PNG data
        with escape sequences for positioning and display.

        Args:
            data: Image data (PNG, JPEG, etc.)
            max_width: Max width in terminal cells.
            max_height: Max height in terminal rows.

        Returns:
            Tuple of (kitty escape sequence string, dimensions).
        """
        import base64
        from PIL import Image

        # Load and resize image
        image = self.load_image(data)

        # Convert to RGB if necessary (Kitty needs RGB/RGBA)
        if image.mode not in ('RGB', 'RGBA'):
            image = image.convert('RGBA')

        # Resize to fit terminal
        image, dims = self.resize_image(image, max_width, max_height)

        # Save as PNG to bytes
        output = BytesIO()
        image.save(output, format='PNG')
        png_data = output.getvalue()

        # Build Kitty graphics escape sequence
        # Format: \033_G<key>=<value>,...;<payload>\033\\
        # We use: a=T (transmit), f=100 (PNG), chunked transmission

        b64_data = base64.standard_b64encode(png_data).decode('ascii')

        # Kitty recommends chunks of 4096 bytes
        chunk_size = 4096
        chunks = [b64_data[i:i+chunk_size] for i in range(0, len(b64_data), chunk_size)]

        result = []
        for i, chunk in enumerate(chunks):
            is_last = (i == len(chunks) - 1)
            # m=0 means last chunk, m=1 means more coming
            m_value = 0 if is_last else 1

            if i == 0:
                # First chunk includes format and action
                # a=T: transmit and display
                # f=100: PNG format
                # c,r: columns and rows to display (optional, for sizing)
                result.append(f"\033_Ga=T,f=100,m={m_value};{chunk}\033\\")
            else:
                # Subsequent chunks just have m and payload
                result.append(f"\033_Gm={m_value};{chunk}\033\\")

        return ''.join(result), dims

    def render_kitty_from_png(
        self,
        png_data: bytes,
        cols: int | None = None,
        rows: int | None = None,
    ) -> str:
        """
        Render PNG data directly using Kitty protocol without resizing.

        Useful when you already have appropriately sized PNG data
        (e.g., from browser screenshot).

        Args:
            png_data: PNG image bytes.
            cols: Number of columns to span (optional).
            rows: Number of rows to span (optional).

        Returns:
            Kitty escape sequence string ready to print.
        """
        import base64

        b64_data = base64.standard_b64encode(png_data).decode('ascii')
        chunk_size = 4096
        chunks = [b64_data[i:i+chunk_size] for i in range(0, len(b64_data), chunk_size)]

        result = []
        for i, chunk in enumerate(chunks):
            is_last = (i == len(chunks) - 1)
            m_value = 0 if is_last else 1

            if i == 0:
                # First chunk - include display params
                params = f"a=T,f=100,m={m_value}"
                if cols:
                    params += f",c={cols}"
                if rows:
                    params += f",r={rows}"
                result.append(f"\033_G{params};{chunk}\033\\")
            else:
                result.append(f"\033_Gm={m_value};{chunk}\033\\")

        return ''.join(result)

    def render_placeholder(
        self,
        width: int,
        height: int,
        alt_text: str = "",
    ) -> str:
        """
        Create a text placeholder for images.

        Used when image rendering is disabled or unsupported.

        Args:
            width: Width in cells.
            height: Height in rows.
            alt_text: Alt text to display.

        Returns:
            Text placeholder string.
        """
        if alt_text:
            return f"[image: {alt_text}]"
        return "[image]"


def detect_terminal_capabilities() -> dict:
    """
    Detect terminal graphics capabilities.

    Returns dict with:
        - sixel: bool, Sixel support detected
        - kitty: bool, Kitty protocol supported
        - cell_size: tuple, (width, height) of terminal cells in pixels

    Detection methods:
        - Check $TERM and terminfo
        - Query terminal directly (DA1, Kitty detection)
    """
    import os
    import sys

    capabilities = {
        "sixel": False,
        "kitty": False,
        "cell_size": (8, 16),  # Default assumption
    }

    # Check for Kitty
    if os.environ.get("KITTY_WINDOW_ID"):
        capabilities["kitty"] = True

    # Check TERM for sixel support hints
    term = os.environ.get("TERM", "")
    if "xterm" in term or "mlterm" in term:
        # These often support sixel, but we'd need to query to be sure
        pass

    # TODO: Implement proper terminal querying
    # This would involve:
    # 1. Send DA1 (Primary Device Attributes) query
    # 2. Parse response for sixel support
    # 3. Query Kitty with special sequence

    return capabilities
