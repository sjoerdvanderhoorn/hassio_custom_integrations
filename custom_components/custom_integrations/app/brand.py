"""Render agent-designed, bounded geometric artwork; no URLs, code or SVG execution."""
from io import BytesIO
import math
import re
from PIL import Image, ImageDraw

PNG_PATHS={'brand/icon.png','brand/dark_icon.png','brand/logo.png','brand/dark_logo.png'}
COLOR=re.compile(r'^#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?$')


def color(value):
    if not isinstance(value,str) or not COLOR.fullmatch(value):
        raise ValueError('Icon colors must be #RRGGBB or #RRGGBBAA')
    return value


def validate_png(content, path='brand/icon.png'):
    if len(content)>160_000 or not content.startswith(b'\x89PNG\r\n\x1a\n'):
        raise ValueError('Brand image must be a PNG no larger than 160 KB')
    try:
        with Image.open(BytesIO(content)) as image:
            if image.format!='PNG' or image.width>1024 or image.height>1024:
                raise ValueError('Brand image dimensions exceed 1024 pixels')
            if path.endswith(('icon.png','dark_icon.png')) and image.size not in {(256,256),(512,512)}:
                raise ValueError('Integration icons must be 256×256 or 512×512 pixels')
            if getattr(image,'n_frames',1)!=1:
                raise ValueError('Animated brand images are not supported')
            image.verify()
    except (OSError,SyntaxError,Image.DecompressionBombError) as exc:
        raise ValueError('Invalid or oversized PNG brand image') from exc


def render_icon(background, shapes):
    color(background)
    if not isinstance(shapes,list) or not 1<=len(shapes)<=64:
        raise ValueError('Design the icon with 1 to 64 geometric shapes')
    scale=2
    image=Image.new('RGBA',(512,512),background)
    draw=ImageDraw.Draw(image)
    for shape in shapes:
        if not isinstance(shape,dict) or set(shape)-{'type','points','color','width','radius'}:
            raise ValueError('Invalid icon shape fields')
        kind=shape.get('type');points=shape.get('points');fill=color(shape.get('color'))
        if kind not in {'rectangle','rounded_rectangle','ellipse','line','polygon'}:
            raise ValueError('Unsupported icon shape')
        if not isinstance(points,list) or len(points)%2 or not 4<=len(points)<=128:
            raise ValueError('Icon points must be coordinate pairs on a 256×256 canvas')
        if any(isinstance(n,bool) or not isinstance(n,(int,float)) or not math.isfinite(n) or not 0<=n<=256 for n in points):
            raise ValueError('Icon coordinates must be finite numbers between 0 and 256')
        width=shape.get('width',8);radius=shape.get('radius',16)
        if isinstance(width,bool) or not isinstance(width,int) or not 1<=width<=32:
            raise ValueError('Icon line width must be 1 to 32 pixels')
        if isinstance(radius,bool) or not isinstance(radius,int) or not 0<=radius<=64:
            raise ValueError('Icon corner radius must be 0 to 64 pixels')
        scaled=[round(n*scale) for n in points]
        if kind in {'rectangle','rounded_rectangle','ellipse'}:
            if len(scaled)!=4 or scaled[2]<=scaled[0] or scaled[3]<=scaled[1]:
                raise ValueError('Icon bounds must be [left, top, right, bottom]')
            if kind=='rectangle':draw.rectangle(scaled,fill=fill)
            elif kind=='ellipse':draw.ellipse(scaled,fill=fill)
            else:draw.rounded_rectangle(scaled,radius=radius*scale,fill=fill)
        elif kind=='line':draw.line(list(zip(scaled[::2],scaled[1::2])),fill=fill,width=width*scale,joint='curve')
        else:
            if len(scaled)<6:raise ValueError('An icon polygon needs at least three points')
            draw.polygon(list(zip(scaled[::2],scaled[1::2])),fill=fill)
    image=image.resize((256,256),Image.Resampling.LANCZOS)
    output=BytesIO();image.save(output,format='PNG',optimize=True)
    content=output.getvalue();validate_png(content)
    return content
