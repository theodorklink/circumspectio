"""Circumspectio – Logo-Erzeugung. Bildzeichen: römische Münze (Perlrand) mit Windrose
(16 Blickrichtungen) und dem Monogramm C+S im Medaillon. Ausgabe als SVG; PNG per Browser."""
import math, base64, sys
INK="#1B1B1B"; NAVY="#1F3A5F"; GREY="#6B7078"
def P(cx,cy,r,deg): t=math.radians(deg-90); return cx+r*math.cos(t), cy+r*math.sin(t)
def ln(a,b,c,w): return f'<line x1="{a[0]:.2f}" y1="{a[1]:.2f}" x2="{b[0]:.2f}" y2="{b[1]:.2f}" stroke="{c}" stroke-width="{w:.2f}"/>'
def zeichen(cx,cy,R=130,w=1.0):
    e=[]
    for i in range(72):
        x,y=P(cx,cy,R,i*5); e.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{2.8*w:.2f}" fill="{INK}"/>')
    e.append(f'<circle cx="{cx}" cy="{cy}" r="{R-14}" fill="none" stroke="{INK}" stroke-width="{1.4*w:.2f}"/>')
    for i in range(16):
        d=i*22.5; card=i%4==0; diag=i%2==0
        r2=(R-21) if card else ((R-31) if diag else (R-39))
        e.append(ln(P(cx,cy,86,d),P(cx,cy,r2,d), NAVY if card else GREY, (2.8 if card else (1.4 if diag else 0.9))*w))
    e.append(f'<circle cx="{cx}" cy="{cy}" r="86" fill="none" stroke="{INK}" stroke-width="{1.7*w:.2f}"/>')
    size=168
    e.append(f'<text x="{cx}" y="{cy+size*0.355:.1f}" text-anchor="middle" font-family="CinzelL" font-size="{size}" fill="{INK}">C</text>')
    ss=size*0.5
    e.append(f'<text x="{cx+size*0.10:.1f}" y="{cy+ss*0.355:.1f}" text-anchor="middle" font-family="CinzelL" font-weight="600" font-size="{ss}" fill="{NAVY}">S</text>')
    return "".join(e)
def svg(body,w,h,font):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">'
            f'<style>@font-face{{font-family:"CinzelL";src:url(data:font/ttf;base64,{font});}}</style>'
            f'<rect width="{w}" height="{h}" fill="#FFFFFF"/>{body}</svg>')
def logo(font):
    body = zeichen(600,140,w=1.5) + (f'<text x="606" y="378" text-anchor="middle" font-family="CinzelL" '
            f'font-size="78" font-weight="500" letter-spacing="11" fill="{INK}">CIRCUMSPECTIO</text>')
    return svg(body,1200,410,font)
def nur_zeichen(font): return svg(zeichen(140,140,w=1.9),280,280,font)
if __name__=="__main__":
    font=base64.b64encode(open(sys.argv[1],'rb').read()).decode()
    open('logo.svg','w').write(logo(font)); open('zeichen.svg','w').write(nur_zeichen(font))
