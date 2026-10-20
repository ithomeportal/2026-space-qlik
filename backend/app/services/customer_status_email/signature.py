"""Magaly Vazquez's e-mail signature, as Xink publishes it.

Fetched read-only from the Xink REST API on 2026-10-20 (signature "UNLK Ops
2026", DefaultNew + DefaultReply for mvazquez@) with each image placeholder
resolved to the URL Xink returns for it. Graph ``sendMail`` does not add the
Outlook add-in signature, and the M365 transport-rule route breaks DKIM
(``/BOT/seamless-pipedrive/docs/SPEC-SEQUENCE-TEMPLATES.md`` §3), so the
signature is part of the body. All images are public HTTPS — no CID
attachments needed. Re-fetch with the seamless-pipedrive Xink client if
Magaly's signature changes.
"""

SIGNATURE_HTML = """
<table border="0" cellpadding="0" cellspacing="0" style="width:600px;">
<tr><td>
<table border="0" cellpadding="0" cellspacing="0" style="max-width:750pt;border-collapse:collapse;">
<tr>
<td style="padding:0 5pt 0 0;" valign="middle"><img border="0" height="60" width="60" alt="Magaly Vazquez" src="https://unlk.tech/codetwo/Magaly.Vazquez.png" /></td>
<td style="padding:0 10pt;" valign="middle"><span style="font-family:aptos,calibri,arial,helvetica,sans-serif;"><span style="font-size:10pt;"><b>Magaly Vazquez</b></span><br />
<span style="font-size:8pt;">Tracking and Tracing<br />
&bull; M: <a href="tel:972 200 0606 Ex: 1060" style="color:#467886;">972 200 0606 Ex: 1060</a><br />
&bull; D: <a href="tel:726 232 8810" style="color:#467886;">726 232 8810</a></span></span></td>
<td style="padding:0 10pt 0 5pt;border-right:1px solid #cccccc;border-left:1px solid #cccccc;" valign="middle"><img alt="Unilink Logo" border="0" height="81" width="180" src="https://i.xink.io/Images/Get/U575/h.png" /></td>
<td style="padding:0 10pt;" valign="middle"><img alt="ISO 9001:2015" border="0" height="30" width="45" src="https://i.xink.io/Images/Get/U575/i435.jpg" /> <img alt="NMSDC" border="0" height="30" width="55" src="https://i.xink.io/Images/Get/U575/i52.jpg" /> <img alt="SmartWay Transport Partner" border="0" height="30" width="65" src="https://i.xink.io/Images/Get/U575/i61.jpg" /></td>
</tr>
<tr><td colspan="5" style="padding:6pt 10pt 0 10pt;text-align:center;"><span style="font-family:aptos,calibri,arial,helvetica,sans-serif;font-size:8pt;">Web: <a href="https://unilinktransportation.com/" style="color:#467886;">unilinktransportation.com</a></span></td></tr>
<tr><td colspan="3" style="padding:10pt;text-align:center;" valign="top"><a href="https://route.unilinkportal.com/report" title="Click here to create a ticket"><img alt="Report a complaint" border="0" height="51" width="150" src="https://i.xink.io/Images/Get/U575/c3.jpg" /></a></td></tr>
</table>
</td></tr>
</table>
"""
