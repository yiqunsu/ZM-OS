import { useRef, useState } from "react";
import { ImageIcon, RotateCcw, ZoomIn, ZoomOut } from "lucide-react";
import { ImagePreview } from "./ImagePreview";
import { attachmentUrl } from "./api";

export default function OrderSourceImage({
  attachmentId,
  label,
}: {
  attachmentId?: string;
  label?: string;
}) {
  const [zoom, setZoom] = useState(1);
  const viewport = useRef<HTMLDivElement>(null);
  const drag = useRef<{
    x: number;
    y: number;
    left: number;
    top: number;
  } | null>(null);
  return (
    <section className="source-panel" aria-label="原始截图">
      <header>
        <span>{label ?? "原始截图"}</span>
        {attachmentId && (
          <ImagePreview
            src={attachmentUrl(attachmentId)}
            alt="原始截图"
            label="放大查看"
          />
        )}
      </header>
      <div
        className="source-viewport"
        ref={viewport}
        onPointerDown={(e) => {
          if (!viewport.current) return;
          drag.current = {
            x: e.clientX,
            y: e.clientY,
            left: viewport.current.scrollLeft,
            top: viewport.current.scrollTop,
          };
          e.currentTarget.setPointerCapture(e.pointerId);
        }}
        onPointerMove={(e) => {
          if (drag.current && viewport.current) {
            viewport.current.scrollLeft =
              drag.current.left - e.clientX + drag.current.x;
            viewport.current.scrollTop =
              drag.current.top - e.clientY + drag.current.y;
          }
        }}
        onPointerUp={() => {
          drag.current = null;
        }}
        onPointerCancel={() => {
          drag.current = null;
        }}
      >
        {attachmentId ? (
          <div
            className="source-canvas"
            style={{ width: `${zoom * 100}%`, height: `${zoom * 100}%` }}
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              draggable={false}
              src={attachmentUrl(attachmentId)}
              alt="当前订单原图"
            />
          </div>
        ) : (
          <div className="workbench-empty">
            <ImageIcon size={32} />
            <p>选择订单，对照原图核对</p>
          </div>
        )}
      </div>
      {attachmentId && (
        <footer>
          <button
            aria-label="缩小截图"
            onClick={() => setZoom((z) => Math.max(1, z - 0.5))}
          >
            <ZoomOut size={16} />
          </button>
          <span>{Math.round(zoom * 100)}%</span>
          <button
            aria-label="放大截图"
            onClick={() => setZoom((z) => Math.min(4, z + 0.5))}
          >
            <ZoomIn size={16} />
          </button>
          <button aria-label="还原截图" onClick={() => setZoom(1)}>
            <RotateCcw size={15} />
          </button>
          <span className="ml-auto">放大后可拖动</span>
        </footer>
      )}
    </section>
  );
}
