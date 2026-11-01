"use client";

import { useMutation } from "@tanstack/react-query";
import { FileSpreadsheet } from "lucide-react";
import { useState } from "react";

import { Field, Input } from "@/components/ui/primitives";
import { Spinner } from "@/components/ui/states";
import { useI18n } from "@/i18n/provider";
import { api, ApiError } from "@/lib/api";

interface ImportPreview {
  rows: { name: string; website: string | null; phone: string | null; line: number; warning?: string }[];
  rejected: { line: number; reason: string }[];
  encoded: string[];
}

const MAX_BYTES = 5 * 1024 * 1024;

function toBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1] ?? "");
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

/** Uploads a CSV/XLSX for server-side validation and hands the validated rows to the form. */
export function ImportUpload({ onRows, error }: { onRows: (rows: string[]) => void; error?: string }) {
  const { t, vmsg } = useI18n();
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const upload = useMutation({
    mutationFn: async (file: File) => {
      if (file.size > MAX_BYTES) throw new Error(t.validation.fileTooLarge);
      const content_base64 = await toBase64(file);
      return api<ImportPreview>("/campaigns/import-preview", {
        method: "POST",
        body: { filename: file.name, content_base64 },
      });
    },
    onSuccess: (data) => {
      setPreview(data);
      onRows(data.encoded);
    },
    onError: () => {
      setPreview(null);
      onRows([]);
    },
  });
  const failure = upload.error instanceof ApiError || upload.error instanceof Error ? upload.error.message : null;

  return (
    <Field label={t.wizard.importFile} htmlFor="import_file" hint={t.wizard.importHint} error={failure ?? vmsg(error)}>
      <div className="space-y-2">
        <Input
          id="import_file"
          type="file"
          accept=".csv,.xlsx,.xlsm,.txt"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) upload.mutate(file);
          }}
        />
        {upload.isPending ? <Spinner /> : null}
        {preview ? (
          <div className="rounded-md border p-3 text-xs" aria-live="polite">
            <p className="flex items-center gap-2 font-medium">
              <FileSpreadsheet className="size-4 text-rasd-500" />
              {t.wizard.importReady.replace("{n}", String(preview.rows.length))}
              {preview.rejected.length ? (
                <span className="text-warning">· {t.wizard.importRejected.replace("{n}", String(preview.rejected.length))}</span>
              ) : null}
            </p>
            <ul className="mt-2 max-h-40 space-y-0.5 overflow-auto text-muted-foreground">
              {preview.rows.slice(0, 8).map((r) => (
                <li key={r.line} className="truncate">
                  {r.name}
                  {r.website ? ` · ${r.website}` : ""}
                  {r.phone ? ` · ${r.phone}` : ""}
                </li>
              ))}
              {preview.rejected.slice(0, 5).map((r) => (
                <li key={`x${r.line}`} className="text-warning">
                  #{r.line}: {r.reason}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    </Field>
  );
}
