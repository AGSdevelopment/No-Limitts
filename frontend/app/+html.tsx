// @ts-nocheck
import { ScrollViewStyleReset } from "expo-router/html";
import type { PropsWithChildren } from "react";

export default function Root({ children }: PropsWithChildren) {
  return (
    <html lang="en" style={{ height: "100%" }}>
      <head>
        <meta charSet="utf-8" />
        <title>No Limitts</title>
        <meta name="theme-color" content="#f7a51d" />
        <meta name="apple-mobile-web-app-title" content="No Limitts" />
        <meta httpEquiv="X-UA-Compatible" content="IE=edge" />
        <meta
          name="viewport"
          content="width=device-width, initial-scale=1, shrink-to-fit=no"
        />
        {/*
          Disable body scrolling on web to make ScrollView components work correctly.
          If you want to enable scrolling, remove `ScrollViewStyleReset` and
          set `overflow: auto` on the body style below.
        */}
        <ScrollViewStyleReset />
        <style
          dangerouslySetInnerHTML={{
            __html: `
              body > div:first-child { position: fixed !important; top: 0; left: 0; right: 0; bottom: 0; }
              [role="tablist"] [role="tab"] * { overflow: visible !important; }
              [role="heading"], [role="heading"] * { overflow: visible !important; }
              html, body { overflow-x: hidden; background: #F3EEE6; }
              /* Desktop & Chromebook: centre the app in a readable column; sheets/dialogs follow the same column */
              @media (min-width: 900px) {
                body > div:first-child { max-width: 1040px; margin: 0 auto; box-shadow: 0 0 40px rgba(0,0,0,0.08); }
                [aria-modal="true"] { max-width: 720px; margin: 0 auto !important; box-shadow: 0 0 0 100vmax rgba(0,0,0,0.35); }
              }
            `,
          }}
        />
      </head>
      <body
        style={{
          margin: 0,
          height: "100%",
          overflow: "hidden",
          display: "flex",
          flexDirection: "column",
        }}
      >
        {children}
      </body>
    </html>
  );
}
