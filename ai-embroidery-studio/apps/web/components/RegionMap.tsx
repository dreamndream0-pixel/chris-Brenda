"use client";
import type { Design, Region } from "@/lib/api";

const ALL_ID = "emb-region-all";
const HIGHLIGHT = "#d23c3c";

// Thread colours close to the fabric background (white, beige) would vanish on the map.
function visible(hex: string | undefined) {
  if (!hex || !/^#[0-9a-f]{6}$/i.test(hex)) return "#777";
  const [r, g, b] = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16) / 255);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.72 ? "#777" : hex;
}

// The design's own region outlines (not stitches). Tapping a shape selects that region; the
// selected one is drawn in red, the rest fade back.
export default function RegionMap({ design, colors, hidden, selected, onSelect }: {
  design: Design; colors: Record<string, string>; hidden: (id: string) => boolean;
  selected: string | null; onSelect: (id: string) => void;
}) {
  const [, , vw, vh] = design.geometry.viewBox;
  const stroke = Math.max(vw, vh) / 150;
  // Draw larger regions first so small ones on top stay tappable.
  const regions = [...design.regions].sort((a, b) => area(b.bbox) - area(a.bbox));
  return (
    <svg viewBox={`0 0 ${vw} ${vh}`} className="block max-h-72 w-full rounded-lg bg-fabric" role="img" aria-label="區域位置圖">
      <defs>
        <g id={ALL_ID}>{design.regions.map(r => <Shape key={r.id} region={r} color="#000" />)}</g>
      </defs>
      {regions.map(r => {
        const on = r.id === selected;
        return (
          <g key={r.id} onClick={() => onSelect(r.id)} className="cursor-pointer"
            opacity={selected ? (on ? 1 : 0.18) : hidden(r.id) ? 0.15 : 0.85}>
            <title>{r.name}</title>
            {on ? <Shape region={r} color={HIGHLIGHT} extra={stroke} /> : <Shape region={r} color={visible(colors[r.colorId])} />}
          </g>
        );
      })}
    </svg>
  );
}

// A small whole-design silhouette with one region highlighted (shares the paths defined above).
export function RegionThumb({ design, regionId }: { design: Design; regionId: string }) {
  const [, , vw, vh] = design.geometry.viewBox;
  const region = design.regions.find(r => r.id === regionId);
  return (
    <svg viewBox={`0 0 ${vw} ${vh}`} className="h-9 w-9 shrink-0 rounded border border-line bg-fabric" aria-hidden>
      <use href={`#${ALL_ID}`} opacity={0.15} />
      {region && <Shape region={region} color={HIGHLIGHT} />}
    </svg>
  );
}

// Areas are filled; line regions (strokes from SVG uploads) are drawn as strokes of their own width.
// `extra` widens the shape into a highlight halo drawn underneath.
function Shape({ region, color, extra = 0 }: { region: Region; color: string; extra?: number }) {
  if (region.shape === "line") {
    return <path d={region.svgPath} fill="none" stroke={color} strokeWidth={(region.strokeWidthUnits ?? 1) + extra}
      strokeLinecap="round" strokeLinejoin="round" />;
  }
  return <path d={region.svgPath} fillRule="evenodd" fill={color} stroke={extra ? color : "none"} strokeWidth={extra}
    strokeLinejoin="round" />;
}

function area(b?: number[]) {
  return b && b.length === 4 ? (b[2] - b[0]) * (b[3] - b[1]) : 0;
}
