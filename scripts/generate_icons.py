import os
import math
import re
from PIL import Image, ImageDraw

def sample_arc(p0, rx, ry, phi_deg, large_arc, sweep, p1, steps=24):
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
        rx *= math.sqrt(radii_check)
        ry *= math.sqrt(radii_check)
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

def sample_cubic_bezier(p0, p1, p2, p3, steps=16):
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

def render_svg(d, stroke_color, stroke_width=1.5, size=192, fill_color=None):
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    scale = size / 24.0

    tokens = re.findall(r'([a-zA-Z])|([-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?)', d)
    cmds = []
    curr_cmd = None
    args = []
    for c, v in tokens:
        if c:
            if curr_cmd:
                cmds.append((curr_cmd, args))
            curr_cmd = c
            args = []
        elif v:
            args.append(float(v))
    if curr_cmd:
        cmds.append((curr_cmd, args))

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
            if len(poly) > 30:
                draw.polygon(poly, fill=fill_color)

    for poly in scaled_polys:
        if len(poly) > 1:
            draw.line(poly, fill=stroke_color, width=w, joint='round')

    return img.resize((32, 32), Image.LANCZOS)

def main():
    img_dir = os.path.join(os.path.dirname(__file__), '..', 'img')
    os.makedirs(img_dir, exist_ok=True)

    refresh_d = "M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0 3.181 3.183a8.25 8.25 0 0 0 13.803-3.7M4.031 9.865a8.25 8.25 0 0 1 13.803-3.7l3.181 3.182m0-4.991v4.99"
    bulb_d = "M12 18v-5.25m0 0a6.01 6.01 0 0 0 1.5-.189m-1.5.189a6.01 6.01 0 0 1-1.5-.189m3.75 7.478a12.06 12.06 0 0 1-4.5 0m3.75 2.383a14.406 14.406 0 0 1-3 0M14.25 18v-.192c0-.983.658-1.823 1.508-2.316a7.5 7.5 0 1 0-7.517 0c.85.493 1.509 1.333 1.509 2.316V18"

    # Refresh icon: Dull default & Bright hover variants
    img_ref_dark = render_svg(refresh_d, stroke_color=(155, 150, 145, 255), stroke_width=1.8)
    img_ref_dark.save(os.path.join(img_dir, 'icon_refresh_dark.png'))

    img_ref_light = render_svg(refresh_d, stroke_color=(130, 125, 120, 255), stroke_width=1.8)
    img_ref_light.save(os.path.join(img_dir, 'icon_refresh_light.png'))

    img_ref_hover_dark = render_svg(refresh_d, stroke_color=(255, 255, 255, 255), stroke_width=1.8)
    img_ref_hover_dark.save(os.path.join(img_dir, 'icon_refresh_hover_dark.png'))

    img_ref_hover_light = render_svg(refresh_d, stroke_color=(20, 20, 25, 255), stroke_width=1.8)
    img_ref_hover_light.save(os.path.join(img_dir, 'icon_refresh_hover_light.png'))

    # Bulb OFF (Dark Mode): Dim neutral silver/grey outline, unlit
    img_bulb_off = render_svg(bulb_d, stroke_color=(180, 185, 195, 255), stroke_width=1.8)
    img_bulb_off.save(os.path.join(img_dir, 'icon_bulb_off.png'))

    # Bulb ON (Light Mode): Glowing warm amber/yellow fill + dark golden stroke
    img_bulb_on = render_svg(bulb_d, stroke_color=(217, 119, 6, 255), stroke_width=1.8, fill_color=(251, 191, 36, 220))
    img_bulb_on.save(os.path.join(img_dir, 'icon_bulb_on.png'))

    print("Icons generated successfully!")

if __name__ == '__main__':
    main()
