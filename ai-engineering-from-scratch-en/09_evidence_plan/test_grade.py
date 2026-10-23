# -*- coding: utf-8 -*-
import lab
good = """plan...
| No. | Task | Must finish first (No.) |
|---|---|---|
| 1 | Legal review of the new return-policy wording | - |
| 2 | Change the intake-screen setting to 14 days (deploy Mon-Thu, no Friday) | 1 |
| 3 | Update the customer-notice template wording (website + SMS) | 1 |
| 4 | Post the notice on the website | 3 |
| 5 | Pull the opted-in customer list (12,000) | - |
| 6 | Send the SMS notice to opted-in customers | 2, 3, 5 |
| 7 | Update the agent manual and chatbot wording | 1 |
| 8 | Agent training | 7 |"""
g = lab.grade(good)
print("sms after legal/system True, web after legal True, template/consent/friday True expected:", g["sms_after_legal"], g["sms_after_system"], g["web_after_legal"], g["template"], g["consent"], g["friday"], "| kinds", g["kinds"], "| waves", g["waves"])
bad = """| No. | Task | Must finish first (No.) |
|---|---|---|
| 1 | Draft the SMS notice | - |
| 2 | Send the SMS to all customers | 1 |
| 3 | Legal review | - |
| 4 | Change the system setting | 3 |"""
g = lab.grade(bad)
print("sms after legal False, after system False expected:", g["sms_after_legal"], g["sms_after_system"], "| kinds", g["kinds"])
print("'Prepare SMS send list' is prep:", lab.kind_of("Prepare the SMS send list"), "| 'Send SMS to opted-in customers' is sms:", lab.kind_of("Send SMS to opted-in customers"), "| 'Deploy setting and send SMS' is system:", lab.kind_of("Deploy the setting change and send the SMS"))
