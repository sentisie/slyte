import io
import qrcode
from PIL import Image, ImageDraw, ImageFont
from typing import Optional, Tuple

def generate_qr(data: str, 
                logo_path: Optional[str] = None, 
                title: Optional[str] = None,
                size: int = 10,
                border: int = 2) -> io.BytesIO:
    """
    Generate a QR code from data
    
    Args:
        data: The data to encode in the QR code
        logo_path: Optional path to logo image to place in center
        title: Optional title to place below QR code
        size: Size of QR code (default: 10)
        border: Border size (default: 2)
        
    Returns:
        BytesIO object with the QR code image
    """
    # Create QR code instance
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=size,
        border=border,
    )
    
    # Add data to the QR code
    qr.add_data(data)
    qr.make(fit=True)
    
    # Create an image from the QR code
    qr_image = qr.make_image(fill_color="black", back_color="white").convert('RGBA')
    
    # Add logo if provided
    if logo_path:
        try:
            logo = Image.open(logo_path).convert('RGBA')
            
            # Calculate logo size (25% of QR code)
            logo_max_size = qr_image.size[0] // 4
            logo.thumbnail((logo_max_size, logo_max_size), Image.LANCZOS)
            
            # Calculate position (center)
            logo_pos = ((qr_image.size[0] - logo.size[0]) // 2,
                        (qr_image.size[1] - logo.size[1]) // 2)
            
            # Create a white background for the logo
            logo_bg = Image.new('RGBA', logo.size, (255, 255, 255, 255))
            qr_image.paste(logo_bg, logo_pos, logo_bg)
            qr_image.paste(logo, logo_pos, logo)
        except Exception as e:
            print(f"Error adding logo: {e}")
    
    # Add title if provided
    if title:
        # Calculate new image dimensions to accommodate title
        title_height = size * 3
        new_img = Image.new('RGBA', 
                          (qr_image.size[0], qr_image.size[1] + title_height), 
                          (255, 255, 255, 255))
        
        # Paste QR code at the top
        new_img.paste(qr_image, (0, 0))
        
        # Add title text
        draw = ImageDraw.Draw(new_img)
        
        # Use a default font
        try:
            font = ImageFont.load_default()
            
            # Calculate text position (center horizontally, below QR code)
            text_bbox = draw.textbbox((0, 0), title, font=font)
            text_width = text_bbox[2] - text_bbox[0]
            text_pos = ((new_img.size[0] - text_width) // 2, qr_image.size[1] + (title_height // 2))
            
            # Draw text
            draw.text(text_pos, title, fill="black", font=font)
            
            qr_image = new_img
        except Exception as e:
            print(f"Error adding title: {e}")
    
    # Convert image to bytes
    img_byte_array = io.BytesIO()
    qr_image.save(img_byte_array, format='PNG')
    img_byte_array.seek(0)
    
    return img_byte_array

def generate_vless_qr(link: str, title: Optional[str] = None) -> io.BytesIO:
    """
    Generate a QR code for a VLESS configuration link
    
    Args:
        link: The VLESS configuration link
        title: Optional title for the QR code
        
    Returns:
        BytesIO object with the QR code image
    """
    return generate_qr(link, title=title, size=10, border=4) 