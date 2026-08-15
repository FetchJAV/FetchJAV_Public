import os
import math
import re
from PIL import Image, ImageDraw

def sample_arc(p0, rx, ry, phi_deg, large_arc, sweep, p1, steps=32):
    x1, y1 = p0
    x2, y2 = p1
    if (x1, y1) == (x2, y2):
        return [p1]
    rx, ry = abs(rx), abs(ry)
    if rx == 0 or ry == 0:
        return [p1]

    phi = math.radians(phi_deg % 360)
    cos_phi = math.cos(phi)
    sin_phi = math.sin(phi)

    dx2 = (x1 - x2) / 2.0
    dy2 = (y1 - y2) / 2.0
    x1_p = cos_phi * dx2 + sin_phi * dy2
    y1_p = -sin_phi * dx2 + cos_phi * dy2

    rx_sq = rx * rx
    ry_sq = ry * ry
    x1_p_sq = x1_p * x1_p
    y1_p_sq = y1_p * y1_p

    radii_check = x1_p_sq / rx_sq + y1_p_sq / ry_sq
    if radii_check > 1:
        scale_f = math.sqrt(radii_check)
        rx *= scale_f
        ry *= scale_f
        rx_sq = rx * rx
        ry_sq = ry * ry

    sign = -1.0 if large_arc == sweep else 1.0
    num = max(0.0, rx_sq * ry_sq - rx_sq * y1_p_sq - ry_sq * x1_p_sq)
    den = rx_sq * y1_p_sq + ry_sq * x1_p_sq
    coef = sign * math.sqrt(num / den) if den != 0 else 0
    cx_p = coef * (rx * y1_p / ry)
    cy_p = coef * (-ry * x1_p / rx)

    cx = cos_phi * cx_p - sin_phi * cy_p + (x1 + x2) / 2.0
    cy = sin_phi * cx_p + cos_phi * cy_p + (y1 + y2) / 2.0

    def angle(u, v):
        dot = u[0]*v[0] + u[1]*v[1]
        len_u = math.hypot(u[0], u[1])
        len_v = math.hypot(v[0], v[1])
        if len_u * len_v == 0:
            return 0
        ang = math.acos(max(-1.0, min(1.0, dot / (len_u * len_v))))
        if u[0]*v[1] - u[1]*v[0] < 0:
            ang = -ang
        return ang

    v1 = ((x1_p - cx_p) / rx, (y1_p - cy_p) / ry)
    v2 = ((-x1_p - cx_p) / rx, (-y1_p - cy_p) / ry)
    theta1 = angle((1, 0), v1)
    dtheta = angle(v1, v2)
    if not sweep and dtheta > 0:
        dtheta -= 2 * math.pi
    elif sweep and dtheta < 0:
        dtheta += 2 * math.pi

    pts = []
    for i in range(1, steps + 1):
        t = theta1 + dtheta * (i / steps)
        x_p = rx * math.cos(t)
        y_p = ry * math.sin(t)
        x = cos_phi * x_p - sin_phi * y_p + cx
        y = sin_phi * x_p + cos_phi * y_p + cy
        pts.append((x, y))
    return pts

def sample_cubic_bezier(p0, p1, p2, p3, steps=24):
    pts = []
    x0, y0 = p0
    x1, y1 = p1
    x2, y2 = p2
    x3, y3 = p3
    for i in range(1, steps + 1):
        t = i / steps
        mt = 1.0 - t
        x = mt**3 * x0 + 3 * mt**2 * t * x1 + 3 * mt * t**2 * x2 + t**3 * x3
        y = mt**3 * y0 + 3 * mt**2 * t * y1 + 3 * mt * t**2 * y2 + t**3 * y3
        pts.append((x, y))
    return pts

def tokenize_d(d):
    raw = re.findall(r'([a-zA-Z])|([-+]?(?:(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?))', d)
    tokens = []
    for c, num in raw:
        if c:
            tokens.append(c)
        elif num:
            tokens.append(num)
    return tokens

def parse_svg_path(d):
    tokens = tokenize_d(d)
    cmds = []
    i = 0
    n = len(tokens)
    curr_cmd = None
    while i < n:
        tok = tokens[i]
        if tok.isalpha():
            curr_cmd = tok
            i += 1
            args = []
            while i < n and not tokens[i].isalpha():
                args.append(float(tokens[i]))
                i += 1
            cmds.append((curr_cmd, args))
        else:
            args = []
            while i < n and not tokens[i].isalpha():
                args.append(float(tokens[i]))
                i += 1
            effective = 'L' if curr_cmd == 'M' else ('l' if curr_cmd == 'm' else curr_cmd)
            cmds.append((effective, args))
    return cmds

def render_svg(d, stroke_color, stroke_width=1.8, canvas_size=256, target_size=32, fill_color=None, view_box=24.0):
    img = Image.new('RGBA', (canvas_size, canvas_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    scale = canvas_size / float(view_box)

    cmds = parse_svg_path(d)
    polylines = []
    curr_poly = []
    cur = (0.0, 0.0)
    start_pt = (0.0, 0.0)

    for cmd_char, args_list in cmds:
        is_rel = cmd_char.islower()
        cmd = cmd_char.upper()
        i = 0
        n = len(args_list)

        while i < n or cmd == 'Z':
            if cmd == 'M':
                x = args_list[i] + (cur[0] if is_rel else 0)
                y = args_list[i+1] + (cur[1] if is_rel else 0)
                i += 2
                cur = (x, y)
                start_pt = (x, y)
                if curr_poly:
                    polylines.append(curr_poly)
                curr_poly = [(x, y)]
                cmd = 'L'
            elif cmd == 'L':
                x = args_list[i] + (cur[0] if is_rel else 0)
                y = args_list[i+1] + (cur[1] if is_rel else 0)
                i += 2
                cur = (x, y)
                curr_poly.append((x, y))
            elif cmd == 'H':
                x = args_list[i] + (cur[0] if is_rel else 0)
                y = cur[1]
                i += 1
                cur = (x, y)
                curr_poly.append((x, y))
            elif cmd == 'V':
                x = cur[0]
                y = args_list[i] + (cur[1] if is_rel else 0)
                i += 1
                cur = (x, y)
                curr_poly.append((x, y))
            elif cmd == 'A':
                if i + 7 > n:
                    break
                rx = args_list[i]
                ry = args_list[i+1]
                rot = args_list[i+2]
                large = int(args_list[i+3])
                sweep = int(args_list[i+4])
                x = args_list[i+5] + (cur[0] if is_rel else 0)
                y = args_list[i+6] + (cur[1] if is_rel else 0)
                i += 7
                arc_pts = sample_arc(cur, rx, ry, rot, large, sweep, (x, y))
                curr_poly.extend(arc_pts)
                cur = (x, y)
            elif cmd == 'C':
                if i + 6 > n:
                    break
                x1 = args_list[i] + (cur[0] if is_rel else 0)
                y1 = args_list[i+1] + (cur[1] if is_rel else 0)
                x2 = args_list[i+2] + (cur[0] if is_rel else 0)
                y2 = args_list[i+3] + (cur[1] if is_rel else 0)
                x = args_list[i+4] + (cur[0] if is_rel else 0)
                y = args_list[i+5] + (cur[1] if is_rel else 0)
                i += 6
                c_pts = sample_cubic_bezier(cur, (x1, y1), (x2, y2), (x, y))
                curr_poly.extend(c_pts)
                cur = (x, y)
            elif cmd == 'Z':
                curr_poly.append(start_pt)
                polylines.append(curr_poly)
                curr_poly = []
                break
            else:
                break
    if curr_poly:
        polylines.append(curr_poly)

    scaled_polys = [[(x * scale, y * scale) for x, y in poly] for poly in polylines]
    w = max(1, int(stroke_width * scale))

    if fill_color:
        for poly in scaled_polys:
            if len(poly) > 2:
                draw.polygon(poly, fill=fill_color)

    if stroke_color:
        for poly in scaled_polys:
            if len(poly) > 1:
                draw.line(poly, fill=stroke_color, width=w, joint='round')

    return img.resize((target_size, target_size), Image.LANCZOS)

def generate_multi_resolution_ico(master_png_path, ico_output_path):
    master = Image.open(master_png_path).convert('RGBA')
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    master.save(ico_output_path, format='ICO', sizes=sizes)

def main():
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    img_dir = os.path.join(root_dir, 'img')
    os.makedirs(img_dir, exist_ok=True)

    # 1. High quality SVG paths
    refresh_d = "M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0 3.181 3.183a8.25 8.25 0 0 0 13.803-3.7M4.031 9.865a8.25 8.25 0 0 1 13.803-3.7l3.181 3.182m0-4.991v4.99"
    bulb_d = "M12 18v-5.25m0 0a6.01 6.01 0 0 0 1.5-.189m-1.5.189a6.01 6.01 0 0 1-1.5-.189m3.75 7.478a12.06 12.06 0 0 1-4.5 0m3.75 2.383a14.406 14.406 0 0 1-3 0M14.25 18v-.192c0-.983.658-1.823 1.508-2.316a7.5 7.5 0 1 0-7.517 0c.85.493 1.509 1.333 1.509 2.316V18"
    search_d = "M21 21l-5.197-5.197m0 0A7.5 7.5 0 1 0 5.196 5.196a7.5 7.5 0 0 0 10.607 10.607z"
    compass_d = "M12 22A10 10 0 1 0 12 2a10 10 0 0 0 0 20z M16.24 7.76l-2.12 6.36-6.36 2.12 2.12-6.36 6.36-2.12z"
    download_d = "M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5M16.5 12 12 16.5m0 0L7.5 12m4.5 4.5V3"
    settings_d = "M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 0 0 2.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 0 0 1.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 0 0-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 0 0-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 0 0-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 0 0-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 0 0 1.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0z"
    browse_d = "M2.25 12.75V12A2.25 2.25 0 0 1 4.5 9.75h15A2.25 2.25 0 0 1 21.75 12v.75m-8.69-6.44-2.12-2.12a1.5 1.5 0 0 0-1.061-.44H4.5A2.25 2.25 0 0 0 2.25 6v12a2.25 2.25 0 0 0 2.25 2.25h15A2.25 2.25 0 0 0 21.75 18V9a2.25 2.25 0 0 0-2.25-2.25h-5.379a1.5 1.5 0 0 1-1.06-.44z"
    trash_d = "M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0"
    heart_d = "M21 8.25c0-2.485-2.099-4.5-4.688-4.5-1.935 0-3.597 1.126-4.312 2.733-.715-1.607-2.377-2.733-4.313-2.733C5.1 3.75 3 5.765 3 8.25c0 7.22 9 12 9 12s9-4.78 9-12z"
    plus_d = "M12 4.5v15m7.5-7.5h-15"
    open_d = "M13.5 6H5.25A2.25 2.25 0 0 0 3 8.25v10.5A2.25 2.25 0 0 0 5.25 21h10.5A2.25 2.25 0 0 0 18 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25"
    tag_d = "M9.568 3H5.25A2.25 2.25 0 0 0 3 5.25v4.318c0 .597.237 1.17.659 1.591l9.581 9.581c.699.699 1.78.872 2.607.386a11.166 11.166 0 0 0 3.99-3.99c.486-.827.313-1.908-.386-2.607l-9.581-9.581A2.25 2.25 0 0 0 9.568 3z M6 6h.008v.008H6V6z"
    list_select_d = "M9 6h11M9 12h11M9 18h11M4 6h.01M4 12h.01M4 18h.01"

    # Search icon variants
    render_svg(search_d, stroke_color=(235, 235, 240, 255), stroke_width=2.0, target_size=48).save(os.path.join(img_dir, 'icon_search.png'))
    render_svg(search_d, stroke_color=(235, 235, 240, 255), stroke_width=2.0, target_size=48).save(os.path.join(img_dir, 'icon_sub_search_dark.png'))
    render_svg(search_d, stroke_color=(45, 45, 55, 255), stroke_width=2.0, target_size=48).save(os.path.join(img_dir, 'icon_sub_search_light.png'))

    # Compass icon variants (High visibility & contrast for Search From All toggle)
    render_svg(compass_d, stroke_color=(215, 215, 225, 255), stroke_width=1.9, target_size=32).save(os.path.join(img_dir, 'icon_compass_dark.png'))
    render_svg(compass_d, stroke_color=(50, 50, 60, 255), stroke_width=1.9, target_size=32).save(os.path.join(img_dir, 'icon_compass_light.png'))
    render_svg(compass_d, stroke_color=(255, 51, 102, 255), stroke_width=2.0, target_size=32, fill_color=(255, 51, 102, 100)).save(os.path.join(img_dir, 'icon_compass_on_dark.png'))
    render_svg(compass_d, stroke_color=(235, 40, 90, 255), stroke_width=2.0, target_size=32, fill_color=(235, 40, 90, 100)).save(os.path.join(img_dir, 'icon_compass_on_light.png'))

    # Refresh icon variants
    render_svg(refresh_d, stroke_color=(175, 175, 185, 255), stroke_width=1.8, target_size=32).save(os.path.join(img_dir, 'icon_refresh_dark.png'))
    render_svg(refresh_d, stroke_color=(75, 75, 85, 255), stroke_width=1.8, target_size=32).save(os.path.join(img_dir, 'icon_refresh_light.png'))
    render_svg(refresh_d, stroke_color=(255, 255, 255, 255), stroke_width=1.9, target_size=32).save(os.path.join(img_dir, 'icon_refresh_hover_dark.png'))
    render_svg(refresh_d, stroke_color=(20, 20, 25, 255), stroke_width=1.9, target_size=32).save(os.path.join(img_dir, 'icon_refresh_hover_light.png'))

    # Bulb theme toggle icon variants
    render_svg(bulb_d, stroke_color=(180, 185, 195, 255), stroke_width=1.8, target_size=32).save(os.path.join(img_dir, 'icon_bulb_off.png'))
    render_svg(bulb_d, stroke_color=(217, 119, 6, 255), stroke_width=1.8, target_size=32, fill_color=(251, 191, 36, 220)).save(os.path.join(img_dir, 'icon_bulb_on.png'))

    # Navigation tabs (Explore, Download, Settings)
    render_svg(compass_d, stroke_color=(255, 51, 102, 255), stroke_width=2.0, target_size=64, fill_color=(255, 51, 102, 80)).save(os.path.join(img_dir, 'icon_explore_active.png'))
    render_svg(compass_d, stroke_color=(150, 150, 160, 255), stroke_width=1.8, target_size=64).save(os.path.join(img_dir, 'icon_explore_inactive.png'))

    render_svg(download_d, stroke_color=(255, 51, 102, 255), stroke_width=2.0, target_size=64).save(os.path.join(img_dir, 'icon_download_active.png'))
    render_svg(download_d, stroke_color=(150, 150, 160, 255), stroke_width=1.8, target_size=64).save(os.path.join(img_dir, 'icon_download_inactive.png'))
    render_svg(download_d, stroke_color=(255, 255, 255, 255), stroke_width=1.8, target_size=64).save(os.path.join(img_dir, 'icon_dl_white.png'))

    render_svg(settings_d, stroke_color=(255, 51, 102, 255), stroke_width=2.0, target_size=64).save(os.path.join(img_dir, 'icon_settings_active.png'))
    render_svg(settings_d, stroke_color=(150, 150, 160, 255), stroke_width=1.8, target_size=64).save(os.path.join(img_dir, 'icon_settings_inactive.png'))

    # Folder Browse icon
    render_svg(browse_d, stroke_color=(220, 220, 230, 255), stroke_width=1.8, target_size=64).save(os.path.join(img_dir, 'icon_browse_dark.png'))
    render_svg(browse_d, stroke_color=(60, 60, 70, 255), stroke_width=1.8, target_size=64).save(os.path.join(img_dir, 'icon_browse_light.png'))
    render_svg(browse_d, stroke_color=(255, 255, 255, 255), stroke_width=2.0, target_size=64).save(os.path.join(img_dir, 'icon_browse_hover_dark.png'))
    render_svg(browse_d, stroke_color=(20, 20, 25, 255), stroke_width=2.0, target_size=64).save(os.path.join(img_dir, 'icon_browse_hover_light.png'))

    # Action icons
    render_svg(list_select_d, stroke_color=(220, 220, 230, 255), stroke_width=2.0, target_size=64).save(os.path.join(img_dir, 'icon_list_select.png'))
    render_svg(trash_d, stroke_color=(220, 220, 230, 255), stroke_width=1.8, target_size=24).save(os.path.join(img_dir, 'icon_trash_dark.png'))
    render_svg(trash_d, stroke_color=(60, 60, 70, 255), stroke_width=1.8, target_size=24).save(os.path.join(img_dir, 'icon_trash_light.png'))

    render_svg(heart_d, stroke_color=(255, 255, 255, 255), stroke_width=1.8, target_size=64).save(os.path.join(img_dir, 'icon_heart_white.png'))
    render_svg(heart_d, stroke_color=(255, 51, 102, 255), stroke_width=2.0, target_size=64).save(os.path.join(img_dir, 'icon_heart_pri.png'))
    render_svg(heart_d, stroke_color=(255, 51, 102, 255), stroke_width=1.8, target_size=64, fill_color=(255, 51, 102, 255)).save(os.path.join(img_dir, 'icon_heart_filled_dark.png'))
    render_svg(heart_d, stroke_color=(235, 40, 90, 255), stroke_width=1.8, target_size=64, fill_color=(235, 40, 90, 255)).save(os.path.join(img_dir, 'icon_heart_filled_light.png'))

    render_svg(plus_d, stroke_color=(255, 255, 255, 255), stroke_width=2.0, target_size=64).save(os.path.join(img_dir, 'icon_plus_white.png'))
    render_svg(plus_d, stroke_color=(255, 51, 102, 255), stroke_width=2.0, target_size=64).save(os.path.join(img_dir, 'icon_plus_pri.png'))

    render_svg(open_d, stroke_color=(220, 220, 230, 255), stroke_width=1.8, target_size=64).save(os.path.join(img_dir, 'icon_open_dark.png'))
    render_svg(open_d, stroke_color=(60, 60, 70, 255), stroke_width=1.8, target_size=64).save(os.path.join(img_dir, 'icon_open_light.png'))
    render_svg(open_d, stroke_color=(255, 255, 255, 255), stroke_width=2.0, target_size=64).save(os.path.join(img_dir, 'icon_open_hover_dark.png'))
    render_svg(open_d, stroke_color=(20, 20, 25, 255), stroke_width=2.0, target_size=64).save(os.path.join(img_dir, 'icon_open_hover_light.png'))

    render_svg(tag_d, stroke_color=(200, 200, 210, 255), stroke_width=1.8, target_size=48).save(os.path.join(img_dir, 'icon_tag_dark.png'))
    render_svg(tag_d, stroke_color=(70, 70, 80, 255), stroke_width=1.8, target_size=48).save(os.path.join(img_dir, 'icon_tag_light.png'))
    render_svg(tag_d, stroke_color=(255, 51, 102, 255), stroke_width=1.9, target_size=48).save(os.path.join(img_dir, 'icon_tag_accent_dark.png'))
    render_svg(tag_d, stroke_color=(235, 40, 90, 255), stroke_width=1.9, target_size=48).save(os.path.join(img_dir, 'icon_tag_accent_light.png'))

    # Subtitle icons
    render_svg(browse_d, stroke_color=(220, 220, 230, 255), stroke_width=1.8, target_size=48).save(os.path.join(img_dir, 'icon_sub_local_dark.png'))
    render_svg(browse_d, stroke_color=(60, 60, 70, 255), stroke_width=1.8, target_size=48).save(os.path.join(img_dir, 'icon_sub_local_light.png'))

    # 2. Multi-resolution ICO and logo variants generated from master FetchJAV logo
    master_logo_p = os.path.join(img_dir, 'logo.png')
    if os.path.isfile(master_logo_p):
        master_img = Image.open(master_logo_p).convert('RGBA')
        
        # Save root and img multi-resolution ico files (16..256)
        generate_multi_resolution_ico(master_logo_p, os.path.join(root_dir, 'logo.ico'))
        generate_multi_resolution_ico(master_logo_p, os.path.join(img_dir, 'favicon.ico'))

        # Save root logo.png (256x256)
        master_img.resize((256, 256), Image.LANCZOS).save(os.path.join(root_dir, 'logo.png'))

        # Save favicons (16, 32, 48, 64, 128, 256, 512)
        for s in [16, 32, 48, 64, 128, 256, 512]:
            master_img.resize((s, s), Image.LANCZOS).save(os.path.join(img_dir, f'favicon-{s}x{s}.png'))

        # Save apple-touch-icons
        master_img.resize((180, 180), Image.LANCZOS).save(os.path.join(img_dir, 'apple-touch-icon.png'))
        master_img.resize((120, 120), Image.LANCZOS).save(os.path.join(img_dir, 'apple-touch-icon-120x120.png'))
        master_img.resize((114, 114), Image.LANCZOS).save(os.path.join(img_dir, 'apple-touch-icon-114x114.png'))
        master_img.resize((57, 57), Image.LANCZOS).save(os.path.join(img_dir, 'apple-touch-icon-57x57.png'))

    print("All vector icons and multi-resolution logo assets generated successfully!")

if __name__ == '__main__':
    main()
