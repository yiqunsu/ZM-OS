"use client";

import { Popover } from "@base-ui/react/popover";

export default function OrderFieldHint({ issues, label }: {
  issues: { code: string; message: string }[];
  label: string;
}) {
  if (!issues.length) return null;
  const title = issues.every((i) => i.code === "UNIT_INFERRED") ? "核对单位" : "需要核对";
  return (
    <Popover.Root>
      <Popover.Trigger nativeButton={false} render={<span role="button" tabIndex={0} />} aria-label={`${label}：${title}`} className="order-field-hint">
        ▸ {title}
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Positioner side="bottom" align="start" sideOffset={6} collisionPadding={12} className="z-[80]">
          <Popover.Popup className="w-72 max-w-[calc(100vw-24px)] rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs leading-6 text-amber-900 shadow-lg outline-none" aria-label={`${label}核对说明`}>
            {issues.map((issue, index) => <p key={index}>{issue.message}</p>)}
          </Popover.Popup>
        </Popover.Positioner>
      </Popover.Portal>
    </Popover.Root>
  );
}
