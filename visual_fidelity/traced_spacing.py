"""Restore advance widths after replacing Latin outlines with measured contours."""

def fit_traced_advances(traced, donor, letters):
    """Fit a same-UPM TrueType derivative to the donor's left/right side bearings.

    Updates the supplied font in place. Plain Latin composites built from the
    traced base plus one or more translated accent marks retain the base advance.
    The accents follow the change in the base's ink center, retaining their
    original horizontal offsets. Unrelated glyphs and pair kerning are preserved.
    """
    if traced["head"].unitsPerEm != donor["head"].unitsPerEm:
        raise ValueError("Donor and replacement must use the same units per em")
    cmap, original_cmap = traced.getBestCmap(), donor.getBestCmap()
    glyphs, original = traced["glyf"], donor["glyf"]
    metrics, original_metrics = traced["hmtx"], donor["hmtx"]
    shifts = {}
    for char in dict.fromkeys(letters):
        key = cmap[ord(char)]
        source = original_cmap[ord(char)]
        glyph, old = glyphs[key], original[source]
        glyph.recalcBounds(glyphs)
        if glyph.xMin != old.xMin:
            raise ValueError("Align the trace to the donor's left ink edge first")
        advance, bearing = original_metrics[source]
        width_change = glyph.xMax - old.xMax
        metrics[key] = (advance + width_change, bearing)
        shifts[key] = width_change

    for name in glyphs.keys():
        g = glyphs[name]
        if not g.isComposite() or name in shifts or name not in original:
            continue
        base, *marks = g.components
        if base.glyphName not in shifts or not marks:
            continue
        # Only inherit metrics from an untranslated, untransformed base. Anchors
        # attached by point indices follow outlines and are not XY offsets.
        if not hasattr(base, "x") or base.getComponentInfo()[1] != (1, 0, 0, 1, 0, 0) or not (base.flags & 0x0200):
            continue
        orig = original[name]
        if not orig.isComposite() or len(orig.components) != len(g.components):
            continue
        pairs = list(zip(marks, orig.components[1:]))
        if not all(m.glyphName == old.glyphName and hasattr(m, "x") and hasattr(old, "x")
                   for m, old in pairs):
            continue
        dx = shifts[base.glyphName]
        for mark, old in pairs:
            mark.x = old.x + round(dx / 2)
        g.recalcBounds(glyphs)
        original_advance, original_bearing = original_metrics[name]
        metrics[name] = (original_advance + dx, original_bearing + g.xMin - orig.xMin)
