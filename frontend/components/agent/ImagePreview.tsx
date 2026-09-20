"use client";
import { useEffect, useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

export function ImagePreview({
  src,
  alt,
  label,
  className = "h-24 w-20",
}: {
  src: string;
  alt: string;
  label?: string;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        aria-label={`放大${alt}`}
        onClick={() => setOpen(true)}
        className="rounded-lg focus-visible:ring-2 focus-visible:ring-[#C8331F]/40"
      >
        {label ? (
          <span className="text-xs text-slate-500 underline underline-offset-2">
            {label}
          </span>
        ) : (
          /* eslint-disable-next-line @next/next/no-img-element */
          <img
            src={src}
            alt={alt}
            className={`${className} rounded-lg border border-slate-200 bg-slate-50 object-contain`}
          />
        )}
      </button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-3xl">
          <DialogHeader>
            <DialogTitle>{alt}</DialogTitle>
          </DialogHeader>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={src}
            alt={`${alt}大图`}
            className="mx-auto max-h-[75dvh] max-w-full object-contain"
          />
        </DialogContent>
      </Dialog>
    </>
  );
}

export function PendingImagePreview({
  file,
  index,
}: {
  file: File;
  index: number;
}) {
  const [url, setUrl] = useState("");
  useEffect(() => {
    const next = URL.createObjectURL(file);
    const timer = setTimeout(() => setUrl(next), 0);
    return () => {
      clearTimeout(timer);
      URL.revokeObjectURL(next);
    };
  }, [file]);
  return url ? (
    <ImagePreview src={url} alt={`待发送截图 ${index}`} className="h-24 w-24" />
  ) : (
    <div className="h-24 w-24 animate-pulse rounded-lg bg-slate-100" />
  );
}
