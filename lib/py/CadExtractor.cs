using System;
using System.Collections.Generic;
using Autodesk.Revit.DB;

namespace MepananaCSharp
{
    public class BlockData
    {
        public string Layer   { get; set; }
        public XYZ    Point   { get; set; }
        public double Angle   { get; set; }
        public bool   Mirrored{ get; set; }

        public BlockData(string layer, XYZ point, double angle, bool mirrored)
        {
            Layer    = layer;
            Point    = point;
            Angle    = angle;
            Mirrored = mirrored;
        }
    }

    public class Extractor
    {
        // ── Helpers ────────────────────────────────────────────────────────────

        private static double GetRotationAngle(Transform tr)
        {
            try   { XYZ bx = tr.BasisX; return Math.Atan2(bx.Y, bx.X); }
            catch { return 0.0; }
        }

        private static bool IsMirrored(Transform tr)
        {
            try
            {
                XYZ bx = tr.BasisX, by = tr.BasisY;
                return (bx.X * by.Y - bx.Y * by.X) < 0.0;
            }
            catch { return false; }
        }

        private static bool IsClose(double a, double b, double tol = 1e-6)
        {
            return Math.Abs(a - b) <= tol;
        }

        // ── Public API ─────────────────────────────────────────────────────────

        public static List<BlockData> ExtractBlocks(Document doc, ImportInstance cadInstance)
        {
            var result = new List<BlockData>();

            var opt = new Options
            {
                IncludeNonVisibleObjects = false,
                ComputeReferences        = false
            };

            GeometryElement geo;
            try   { geo = cadInstance.get_Geometry(opt); }
            catch { return result; }

            if (geo == null) return result;

            Walk(geo, cadInstance.GetTransform(), null, result, doc);
            return result;
        }

        // ── Recursive geometry walker ──────────────────────────────────────────

        private static void Walk(
            GeometryElement geos,
            Transform       parentTr,
            string          parentLayer,
            List<BlockData> result,
            Document        doc)
        {
            if (geos == null) return;

            foreach (GeometryObject g in geos)
            {
                var gi = g as GeometryInstance;
                if (gi == null) continue;

                // Accumulate transform
                Transform tr = parentTr;
                try { tr = parentTr.Multiply(gi.Transform); } catch { }

                // Resolve layer from GraphicsStyle
                string layer = null;
                try
                {
                    ElementId gsId = gi.GraphicsStyleId;
                    if (gsId != ElementId.InvalidElementId)
                    {
                        var gs = doc.GetElement(gsId) as GraphicsStyle;
                        if (gs != null && gs.GraphicsStyleCategory != null)
                            layer = gs.GraphicsStyleCategory.Name;
                    }
                }
                catch { }

                // Inherit parent layer if own layer is empty / default
                if (string.IsNullOrEmpty(layer) || layer == "0" || layer == "Defpoints")
                    layer = (!string.IsNullOrEmpty(parentLayer) && parentLayer != "0") ? parentLayer : "0";

                // Record block position (skip origin blocks)
                XYZ worldPt = tr.OfPoint(XYZ.Zero);
                if (!(IsClose(worldPt.X, 0.0) && IsClose(worldPt.Y, 0.0)))
                    result.Add(new BlockData(layer, worldPt, GetRotationAngle(tr), IsMirrored(tr)));

                // Recurse into nested geometry
                try
                {
                    GeometryElement sub = gi.GetSymbolGeometry();
                    if (sub != null) Walk(sub, tr, layer, result, doc);
                }
                catch { }
            }
        }
    }
}
