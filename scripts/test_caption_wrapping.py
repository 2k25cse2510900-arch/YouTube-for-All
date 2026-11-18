from PIL import Image, ImageDraw, ImageFont

font_caption = ImageFont.truetype("C:/Windows/Fonts/NirmalaB.ttf", 42)
img = Image.new("RGB", (1080, 1920), (0, 0, 0))
draw = ImageDraw.Draw(img)

captions_balanced = [
    ("Shot 1", "क्या अटैक ऑन टाइटन का साठ मीटर लंबा..."),
    ("Shot 2", "...विशालकाय टाइटन\nअसल ज़िंदगी में ज़िंदा रह सकता है?"),
    ("Shot 3", "एनिमे में तो टाइटन बिना किसी परेशानी के..."),
    ("Shot 4", "...आसानी से चलते-फिरते दिखाई देते हैं।"),
    ("Shot 5", "लेकिन विज्ञान के नियम बताते हैं कि\nआकार बढ़ते ही..."),
    ("Shot 6", "...जीव का आयतन और भार\nआठ गुना बढ़ जाता है..."),
    ("Shot 7", "...जबकि हड्डियाँ और मांसपेशियाँ\nकेवल चार गुना ही ताकतवर हो पाती हैं!"),
    ("Shot 8", "इसे कहते हैं वर्ग-घन का नियम!\nइस भारी दबाव के कारण..."),
    ("Shot 9", "...टाइटन का पहला कदम ही\nउसकी हड्डियों को..."),
    ("Shot 10", "...चकनाचूर कर देगा,\nऔर वह अपने ही वज़न तले दब जाएगा!"),
    ("Shot 11", "तो अगली बार जब भी आप कोई एनिमे देखें..."),
    ("Shot 12", "...तो भौतिक विज्ञान के इस नियम को\nज़रूर याद रखें!"),
]

print(f"{'Shot':<12} {'Lines':<7} {'Max Line W':<12} {'Pill x0':<10} {'Pill x1':<10} {'Margin':<10} Safe (>=120px)?")
for name, text in captions_balanced:
    lines = text.split("\n")
    line_bboxes = [draw.textbbox((0, 0), l, font=font_caption) for l in lines]
    line_widths = [b[2] - b[0] for b in line_bboxes]
    max_w = max(line_widths)
    x0 = int((1080 - max_w) / 2) - 24
    x1 = int((1080 + max_w) / 2) + 24
    margin = 1080 - x1
    safe = x1 <= 960 and x0 >= 80
    print(f"{name:<12} {len(lines):<7} {max_w:<12} {x0:<10} {x1:<10} {margin:<10} {safe}")
