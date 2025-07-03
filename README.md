# Cloaked_Spam_Email-ESORICS25

Development of HTML emails increases parsing complexity and discrepancies. Owing to parsing and rendering differences, email systems expose a new attack surface: Cloaked Spam Email (CSE). 
CSE exploits the legitimate functions of HTML and Cascading Style Sheets (CSS) to build invisible content for cloaking.
It can stealthily bypass spam engines and deceive users.
However, there is a lack of the understanding of this novel email cloaking threat, let alone a systematic assessment of its threat impacts, leaving a defense gap.

To fill the understanding gap of CSE risk, this paper reveals its threat impacts via empirical analysis and real-world measurements.
First, through systematic analysis of CSS rendering features and their applicability to email clients, we identified 16 invisible configurations.
Based on these findings, we conducted a comprehensive evaluation of 14 well-known email services. Our results reveal 12 services vulnerable to CSE, with our constructed spam samples successfully bypassing their detection and reaching victim inboxes, including Gmail, Fastmail, and QQ. 
To systematically assess the impact of CSEs in the wild, we developed a detection framework and applied it to two real-world spam datasets: an open-source spam dataset and the actual logs from a renowned email service provider. Through analyzing a combined total of 8,816,785 emails, we successfully detected 102,156 CSE attacks, highlighting the presence of such threats in the email ecosystem.
Finally, we responsibly disclosed these vulnerabilities to affected email providers and provided mitigation recommendations against CSE threat.

## CSEMiner

extract_htmls_from_emlfile.py: Extract HTML content from .eml file and save as .html file.

invisible_detection-new.py: Check if the text in the html file contains hidden configuration.

## data

- A1-E3: 16 CSS properties and invisible configurations.
- T1M0-X.txt: Original spam content.

## ESORICS 2025

Our research on CSE risks has been accepted for ESORICS 2025. We hope that the public code can help email vendors and users defend against the impact of CSE.
