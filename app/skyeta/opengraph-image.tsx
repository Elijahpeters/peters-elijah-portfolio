import { ImageResponse } from "next/og";

export const alt =
  "SkyETA — compare worldwide flights and understand reliability evidence";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function SkyetaOpenGraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          position: "relative",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          overflow: "hidden",
          padding: "68px 76px",
          color: "#f7fbff",
          background:
            "radial-gradient(circle at 78% 18%, #283285 0, #111741 31%, #06091e 72%)",
        }}
      >
        <div
          style={{
            position: "absolute",
            width: 690,
            height: 690,
            right: -165,
            top: -235,
            border: "2px solid rgba(115,223,255,.34)",
            borderRadius: "50%",
          }}
        />
        <div
          style={{
            position: "absolute",
            width: 950,
            height: 260,
            left: 360,
            top: 135,
            borderTop: "3px dashed rgba(115,223,255,.52)",
            borderRadius: "50%",
            transform: "rotate(-5deg)",
          }}
        />

        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 16,
            color: "#73dfff",
            fontSize: 25,
            fontWeight: 700,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
          }}
        >
          <span
            style={{
              width: 18,
              height: 18,
              display: "flex",
              borderRadius: "50%",
              background: "#61f49b",
              boxShadow: "0 0 0 9px rgba(97,244,155,.12)",
            }}
          />
          Flight search + reliability evidence
        </div>

        <div style={{ display: "flex", flexDirection: "column" }}>
          <div
            style={{
              display: "flex",
              fontSize: 154,
              fontWeight: 800,
              lineHeight: 0.88,
              letterSpacing: "-0.07em",
            }}
          >
            SkyETA
          </div>
          <div
            style={{
              width: 770,
              display: "flex",
              marginTop: 34,
              color: "#cbd8ef",
              fontSize: 32,
              lineHeight: 1.35,
            }}
          >
            Compare current flights worldwide. Understand what the evidence says
            about reliability.
          </div>
        </div>

        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            color: "#9aabd0",
            fontSize: 20,
            letterSpacing: "0.04em",
          }}
        >
          <span>peterselijah.name.ng/skyeta</span>
          <span>Built by Peters Elijah Temidayo</span>
        </div>
      </div>
    ),
    size,
  );
}
