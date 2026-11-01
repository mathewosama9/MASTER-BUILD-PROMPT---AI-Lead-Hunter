from app.research.analysis.ai_service import arabic_register
from app.research.analysis.heuristic import template_pitch


def test_arabic_register_follows_market():
    assert "Egyptian" in arabic_register("EG")
    assert "Gulf" in arabic_register("sa")
    assert "Levantine" in arabic_register("JO")
    assert "Modern Standard" in arabic_register("MA")
    assert "Modern Standard" in arabic_register(None)


def test_template_pitch_uses_egyptian_for_egypt():
    ctx = {"company": "مطعم النيل", "service_name": "تصميم المواقع", "country": "EG"}
    eg = template_pitch(ctx, "ar")
    assert "إحنا" in eg["whatsapp_message"]
    assert "إلغاء" in eg["whatsapp_message"]
    msa = template_pitch({**ctx, "country": "SA"}, "ar")
    assert "إحنا" not in msa["whatsapp_message"]
