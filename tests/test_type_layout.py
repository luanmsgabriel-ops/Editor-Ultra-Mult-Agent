import pytest
from PIL import Image,ImageFont
from visual_fidelity.type_layout import (LetteringLayer,LetteringProvenance,
    compose_layers,text_mask,glyph_metrics,layout_arc,render_arc)


@pytest.fixture
def font():
    return ImageFont.truetype('DejaVuSans.ttf',70)


def test_arc_uses_real_advances_including_pair_kerning(font):
    metrics,width=glyph_metrics('Wi AV',font)
    assert metrics[0]['advance']>metrics[1]['advance']*2
    assert width==pytest.approx(font.getlength('Wi AV',features=['-liga']))
    unkerned=font.getlength('A')+font.getlength('V')
    assert glyph_metrics('AV',font)[1]<unkerned
    layout=layout_arc('Wi AV',font,center=(200,250),radius=170)
    assert len({round(p['angle'],2) for p in layout})==5
    gaps=[layout[i+1]['angle']-layout[i]['angle']for i in range(4)]
    assert max(gaps)-min(gaps)>2


def test_whole_word_alpha_survives_foreground_occlusion():
    lower=Image.new('RGBA',(20,20),(220,0,0,255))
    upper=Image.new('RGBA',(10,10),(255,255,255,255))
    provenance=LetteringProvenance('font',True)
    source=lower.tobytes()
    covered=compose_layers((30,30),[LetteringLayer(lower,provenance),LetteringLayer(upper,provenance,(5,5),1)])
    uncovered=compose_layers((30,30),[LetteringLayer(lower,provenance),LetteringLayer(upper,provenance,(20,20),1)])
    assert covered.getpixel((8,8))==(255,255,255,255)
    assert uncovered.getpixel((8,8))==(220,0,0,255)
    assert lower.tobytes()==source


def test_observed_fragment_cannot_silently_become_complete():
    with pytest.raises(ValueError):LetteringProvenance('observed_fragment',True).validate()
    with pytest.raises(ValueError):
        compose_layers((10,10),[LetteringLayer(Image.new('RGBA',(5,5)),LetteringProvenance('observed_fragment',False))])
    LetteringProvenance('observed_fragment',True,'Hidden stroke authored; not observed').validate()


def test_word_mask_keeps_overhangs_descenders_and_counters(font):
    mask=text_mask('Wag',font,padding=4)
    assert mask.getbbox()[0]>=4
    assert mask.getbbox()[1]>=4
    assert mask.getbbox()[2]<=mask.width-4
    assert mask.getbbox()[3]<=mask.height-4
    assert mask.getextrema()==(0,255)


def test_arc_validation_and_transparent_spaces(font):
    for radius in [0,-1,float('nan')]:
        with pytest.raises(ValueError):layout_arc('ab',font,center=(100,100),radius=radius)
    assert render_arc((100,100),' ',font,center=(50,70),radius=35).getbbox() is None
    with pytest.raises(ValueError):glyph_metrics('a\u0301',font)


def test_tracking_changes_distance_not_uniform_character_angles(font):
    tight,w1=glyph_metrics('Wiii',font,0)
    loose,w2=glyph_metrics('Wiii',font,4)
    assert w2-w1==pytest.approx(12)
    assert loose[3]['origin']-tight[3]['origin']==pytest.approx(12)
