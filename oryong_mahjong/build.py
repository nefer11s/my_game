import re, os

print('majongMain.html 읽는 중...', flush=True)
with open('majongMain.html', 'r', encoding='utf-8') as f:
    text = f.read()

text = re.sub(r'(["\x27\x60])assets/', r'\1../assets/', text)
print('1. 경로 치환 완료', flush=True)

text = text.replace('<title>시연 마작 게임</title>', '<title>오룡이 마작 - 황금용두 테마</title>', 1)
print('2. 타이틀 변경 완료', flush=True)

text = text.replace("'siyeon_mahjong_use_oryong_tiles'", "'oryong_mahjong_use_oryong_tiles'")
text = text.replace("'siyeon_mahjong_oryong_dragon_style'", "'oryong_mahjong_dragon_style'")
text = text.replace("'siyeon_mahjong_use_saju_tiles'", "'oryong_mahjong_use_saju_tiles'")
print('3. localStorage 키 분리 완료', flush=True)

text = text.replace(
    "window.oryongDragonStyle = localStorage.getItem('oryong_mahjong_dragon_style') || 'default';",
    "window.oryongDragonStyle = localStorage.getItem('oryong_mahjong_dragon_style') || 'gold';",
    1
)
print('4. 황금용두 기본값 gold 완료', flush=True)

text = text.replace('<meta property="og:title" content="시연 마작 게임">', '<meta property="og:title" content="오룡이 마작 - 황금용두 테마">', 1)

os.makedirs('oryong_mahjong', exist_ok=True)
out = 'oryong_mahjong/o-ryong_majong.html'
with open(out, 'w', encoding='utf-8') as f:
    f.write(text)
print(f'완료: {out} ({os.path.getsize(out)//1024}KB)')
