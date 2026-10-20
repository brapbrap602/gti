import json
from pathlib import Path
from argparse import ArgumentParser

def generate_html(json_path: Path, output_path: Path):
    """Reads JSON summaries and generates an HTML file."""
    with open(json_path, "r", encoding="utf-8") as jf:
        data = json.load(jf)

    html_content = [
        "<html>",
        "    <head>",
        "        <meta http-equiv=\"Content-Type\" content=\"text/html;charset=utf-8\" />",
        "        <link href=\"style.css\" rel=\"stylesheet\" type=\"text/css\" />",
        "        <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">",
        "        <link rel=\"stylesheet\" href=\"../style.css\">",
        "        <script src=\"../chapter.js\"></script>",
        "        <title>Chapter Summaries - My Longevity Simulation</title>",
        "    </head>",
        "    <body>",
        "        <div class=\"calibre\" id=\"calibre_link-0\">"
    ]

    for entry in data:
        ch_num = entry.get("number")
        title = entry.get("title", f"Chapter {ch_num}")
        summary_sentences = entry.get("sentences", [])
        
        # Match source header
        html_content.append(f"            <h1 id=\"calibre_link-{ch_num}\" class=\"calibre1\">Chapter {ch_num}: {title}</h1>")

        # Individual paragraph for each sentence with calibre2 class
        for sentence in summary_sentences:
            html_content.append(f"            <p class=\"calibre2\">{sentence}</p>")

    html_content.extend([
        "        </div>",
        "    </body>",
        "</html>"
    ])

    output_path.write_text("\n".join(html_content), encoding="utf-8")

def main():
    parser = ArgumentParser(description="Combine JSON summaries into an HTML file.")
    parser.add_argument("json_file", type=str, help="Path to the JSON file containing summaries.")
    parser.add_argument("-o", "--output", type=str, help="Path to the output HTML file.")
    args = parser.parse_args()

    json_path = Path(args.json_file)
    if not json_path.exists():
        print(f"Error: JSON file not found: {json_path}")
        return

    output_path = Path(args.output) if args.output else json_path.with_suffix(".html")
    
    generate_html(json_path, output_path)
    print(f"HTML file generated: {output_path}")

if __name__ == "__main__":
    main()
