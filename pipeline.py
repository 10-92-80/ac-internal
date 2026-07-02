def build_html(by_resp, sb, fu, total, con_cands):
    today    = date.today()
    date_str = today.strftime("%d/%m/%Y")

    max_top = max(len(by_resp[r]) for r in ["CCF","LCT","MGM"])
    max_bot = max(len(by_resp["AHBV"]), len(by_resp["SLR"]), len(sb), len(fu))

    def thead(lbls, subs):
        h = "<thead><tr>"
        for i,l in enumerate(lbls):
            sep = "border-right:2px solid #eebb63;" if i<2 else ""
            h += f'<th colspan="3" class="rh" style="{sep}">{l}</th>'
        h += "</tr><tr>"
        for i,(s1,s2,s3) in enumerate(subs):
            sep = " csep" if i<2 else ""
            h += f'<th class="sh">{s1}</th><th class="sh">{s2}</th><th class="sh{sep}">{s3}</th>'
        return h + "</tr></thead>"

    H = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width">
<title>Pipeline Albero Capital — {date_str}</title>
<style>
@page{{size:A4 landscape;margin:8mm}}
*{{box-sizing:border-box;margin:0;padding:0;font-family:Arial,sans-serif}}
body{{width:277mm;font-size:8px;background:#fff;padding:4px}}
@media print{{
  *{{-webkit-print-color-adjust:exact!important;print-color-adjust:exact!important}}
  col.cd{{width:46mm}}col.cf{{width:19mm}}col.ce{{width:27mm}}
  #login-overlay{{display:none!important}}
}}
#login-overlay{{
  position:fixed;top:0;left:0;width:100%;height:100%;
  background:#62635e;display:flex;align-items:center;
  justify-content:center;z-index:9999;
}}
#login-box{{
  background:#fff;padding:32px 40px;text-align:center;
  box-shadow:0 4px 24px rgba(0,0,0,0.2);min-width:280px;
}}
#login-box .logo{{
  font-size:18px;font-weight:bold;color:#eebb63;
  background:#62635e;padding:6px 16px;letter-spacing:1px;
  display:inline-block;margin-bottom:20px;
}}
#login-box input{{
  width:100%;padding:8px 10px;font-size:13px;
  border:1px solid #d9d8d2;margin-bottom:12px;
  outline:none;color:#62635e;
}}
#login-box button{{
  width:100%;padding:8px;background:#62635e;color:#eebb63;
  font-size:13px;font-weight:bold;border:none;cursor:pointer;
  letter-spacing:1px;
}}
#login-box button:hover{{background:#4a4b47}}
#login-error{{color:#e53935;font-size:11px;margin-top:6px;display:none}}
#content{{display:none}}
.hdr{{display:flex;justify-content:space-between;align-items:center;border-bottom:1.5px solid #eebb63;margin-bottom:3px;padding-bottom:2px}}
.brand{{font-size:13px;font-weight:bold;color:#eebb63;background:#62635e;padding:3px 9px;letter-spacing:1px}}
.sub{{font-size:8px;color:#62635e;margin-bottom:3px}}
.sep{{height:3px;background:#eebb63;margin:4px 0;opacity:0.35}}
table{{border-collapse:collapse;table-layout:fixed;width:100%}}
.rh{{background:#62635e;color:#eebb63;font-size:8px;font-weight:bold;text-align:center;padding:2px 0}}
.sh{{background:#82827c;color:#f5f4f0;font-size:7px;font-weight:bold;height:11px;line-height:11px;padding:0 2px;white-space:nowrap;overflow:hidden}}
td{{height:11px;line-height:11px;font-size:8px;padding:0 3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;border-bottom:1px solid #d9d8d2;color:#62635e;vertical-align:middle}}
.dc{{display:flex;align-items:center;overflow:hidden}}
.dt2{{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.csep{{border-right:2px solid #d9d8d2}}
.ft{{font-size:7px;color:#82827c;text-align:center;margin-top:3px;border-top:1px solid #d9d8d2;padding-top:2px}}
</style>
<script>
function checkPassword() {{
  var pwd = document.getElementById('pwd').value;
  if (pwd === 'Albero109280') {{
    document.getElementById('login-overlay').style.display = 'none';
    document.getElementById('content').style.display = 'block';
    sessionStorage.setItem('albero_auth', '1');
  }} else {{
    document.getElementById('login-error').style.display = 'block';
  }}
}}
function checkEnter(e) {{ if (e.key === 'Enter') checkPassword(); }}
window.onload = function() {{
  if (sessionStorage.getItem('albero_auth') === '1') {{
    document.getElementById('login-overlay').style.display = 'none';
    document.getElementById('content').style.display = 'block';
  }}
}};
</script>
</head><body>

<div id="login-overlay">
  <div id="login-box">
    <div class="logo">ALBERO CAPITAL</div>
    <div style="font-size:12px;color:#82827c;margin-bottom:16px;">Pipeline — Acceso restringido</div>
    <input type="password" id="pwd" placeholder="Contraseña" onkeypress="checkEnter(event)" autofocus>
    <button onclick="checkPassword()">ENTRAR</button>
    <div id="login-error">Contraseña incorrecta</div>
  </div>
</div>

<div id="content">
<div class="hdr"><div class="brand">ALBERO CAPITAL</div><span style="font-size:8px;color:#82827c">{date_str}</span></div>
<div class="sub">Deals/Pipeline &mdash; Actual Status &nbsp;&middot;&nbsp; Deals vivos: <strong>{total}</strong> &nbsp;|&nbsp; Con candidatos: <strong>{con_cands}</strong></div>
"""

    # TOP: CCF | LCT | MGM
    H += f"<table>{COLGROUP}"
    H += thead(["CCF","LCT","MGM"],[("Deal","Fase","Empresa")]*3)
    H += "<tbody>\n"
    for idx in range(max_top):
        H += "<tr>"
        for ci,r in enumerate(["CCF","LCT","MGM"]):
            t1,t2,t3 = resp_tds(by_resp, r, idx)
            if ci < 2: t3 = re.sub(r"^<td","<td class=\"csep\"",t3)
            H += t1+t2+t3
        H += "</tr>\n"
    H += "</tbody></table>\n"

    H += '<div class="sep"></div>\n'

    # BOTTOM: AHBV | SLR | SB&FU
    H += f"<table>{COLGROUP}"
    H += thead(["AHBV","SLR","STAND-BY &amp; FUTUROS"],
               [("Deal","Fase","Empresa"),("Deal","Fase","Empresa"),("Stand-By","Futuro","")])
    H += "<tbody>\n"
    for idx in range(max_bot):
        H += "<tr>"
        for r in ["AHBV","SLR"]:
            t1,t2,t3 = resp_tds(by_resp, r, idx)
            t3 = re.sub(r"^<td","<td class=\"csep\"",t3)
            H += t1+t2+t3
        s,f,v = sbfu_tds(sb, fu, idx)
        H += s+f+v
        H += "</tr>\n"
    H += "</tbody></table>\n"

    H += f'<div class="ft">Albero Capital &nbsp;&middot;&nbsp; Datos en tiempo real desde Zoho CRM &nbsp;&middot;&nbsp; {date_str}</div>\n'
    H += "</div></body></html>"
    return H
