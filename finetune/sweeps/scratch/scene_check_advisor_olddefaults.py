import importlib.util, sys, torch
sys.path.insert(0, ".")
import vox.generate as G; from vox.generate import Scene
from vox.schema import ACTIONS
from jevlike.data import validate
spec = importlib.util.spec_from_file_location("jt", "students/jevlike/train.py"); mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
R = "hum that {}; pitch change large (over 4 semitones); duration medium (400-1000 ms); tone clear tone; loudness normal; sounds like {}"
CLICK = "a tongue click; instant sound; loudness normal; sounds like mouth sound"
scenes = [
 ("rise", [R.format("rises from low to high","hum")], ("rise",), "swipe_up"),
 ("fall", [R.format("falls from high to low","hum")], ("fall",), "swipe_down"),
 ("dip", [R.format("falls then rises","hum")], ("dip",), "swipe_left"),
 ("arch", [R.format("rises then falls","hum")], ("arch",), "swipe_right"),
 ("click", [CLICK], ("click",), "tap"),
 ("flat", ["hum that stays level; pitch change small (under 2 semitones); duration long (over 1 s); tone clear tone; loudness normal; sounds like hum"], ("flat",), "long_press"),
 ("talking", [R.format("rises from low to high","talking")], ("rise",), "none"),
 ("click rise", [CLICK, R.format("rises from low to high","hum")], ("click","rise"), "none"),
 ("hiss", ["a hiss; duration short (150-400 ms); loudness normal; sounds like mouth sound"], ("hiss",), "back"),
]
G.DEFAULTS_TEXT = "defaults: rise=swipe up, fall=swipe down, arch=swipe right, dip=swipe left, pop=tap, hiss=go back, long flat hum=long-press, click pop=listen for a phrase, click click=go home, hiss click=go back"
keys = list(ACTIONS); opts = [ACTIONS[k] for k in keys]
res = {}
for ck in sys.argv[1:]:
    p = torch.load(ck, map_location="cpu", weights_only=False)
    m, collate = mod.build(p["config"], torch.device("cpu")); m.load_state_dict(p["state_dict"], strict=False); m.eval()
    out = []
    with torch.inference_mode():
        for name, heard, seq, exp in scenes:
            sc = Scene(app="com.android.chrome", heard=heard, sequence=seq)
            b = collate([validate({"context": sc.text(), "options": opts, "label": 0})])
            pr = m(b).float().softmax(-1)[0][:len(opts)]
            i = int(pr.argmax()); out.append((name, exp, keys[i], round(float(pr[i]),3), "OK" if keys[i]==exp else "WRONG"))
    res[ck] = out
for name, _, _, exp in scenes:
    print(f"{name:11s} exp={exp:11s} " + "  ".join(f"{ck.split('/')[-1]}: {r[2]} {r[3]} {r[4]}" for ck, rs in res.items() for r in rs if r[0]==name))
