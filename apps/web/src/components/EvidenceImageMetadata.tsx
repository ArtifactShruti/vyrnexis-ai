export type ImageMetadata = {
  status: "extracted" | "unsupported" | "unreadable" | "no_supported_fields" | "limit_reached" | "unavailable";
  fields: { width?: number; height?: number; orientation?: number; capture_time?: string };
  inspected_at: string;
};

const statusText: Record<ImageMetadata["status"], string> = {
  extracted: "Embedded image fields recorded.",
  unsupported: "Image metadata inspection applies to JPEG and standard TIFF files.",
  unreadable: "The image metadata header could not be read.",
  no_supported_fields: "No supported image fields were found.",
  limit_reached: "The metadata exceeded the inspection limit.",
  unavailable: "Inspection was unavailable. Verify the file to retry.",
};

export default function EvidenceImageMetadata({ metadata }: { metadata: ImageMetadata | null }) {
  const fields = metadata?.fields;
  return <details className="detection-history">
    <summary>Image metadata</summary>
    <p>{metadata ? statusText[metadata.status] : "No inspection recorded. Verify the file to inspect it."}</p>
    {fields && metadata?.status === "extracted" && <ul className="detection-sources">
      {!!fields.width && !!fields.height && <li>Embedded dimensions {fields.width} × {fields.height} pixels</li>}
      {!!fields.width && !fields.height && <li>Embedded width {fields.width} pixels</li>}
      {!!fields.height && !fields.width && <li>Embedded height {fields.height} pixels</li>}
      {!!fields.orientation && <li>EXIF orientation {fields.orientation}</li>}
      {fields.capture_time && <li>Embedded capture time <time dateTime={fields.capture_time}>{fields.capture_time.replace("T", " ")}</time> (time zone unverified)</li>}
    </ul>}
  </details>;
}
