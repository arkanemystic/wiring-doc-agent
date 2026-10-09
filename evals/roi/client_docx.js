// Lays out one client ROI report as a .docx from the block list written by client_docx.py.
// Usage: node client_docx.js spec.json   (NODE_PATH must reach the global `docx` package)
const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, ImageRun, Table, TableRow, TableCell, WidthType, BorderStyle,
  AlignmentType, HeadingLevel, Footer, PageNumber, LevelFormat, TabStopType, VerticalAlign, LineRuleType,
} = require("docx");

const spec = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const INK = "1D1D1B", INK2 = "55534E", MUTED = "8A877F", RULE = "D9D7CF", NAVY = "1F4E8C";
const SERIF = "Georgia", SANS = "Arial";
const PAGE_W = 12240, MARGIN = 1300, CONTENT = PAGE_W - 2 * MARGIN; // DXA, US Letter
const NONE = { style: BorderStyle.NONE, size: 0, color: "FFFFFF" };
const line = (size, color) => ({ style: BorderStyle.SINGLE, size, color });

const textRuns = (runs, opts = {}) =>
  runs.map((r) => new TextRun({ text: r.text, bold: r.bold || opts.bold, color: opts.color, size: opts.size, font: opts.font }));

function table(block) {
  const n = Math.max(...block.rows.map((r) => r.cells.length));
  // First column wider for labels, the rest share what is left.
  const first = n === 2 ? Math.round(CONTENT * 0.62) : Math.round(CONTENT * (n >= 4 ? 0.34 : 0.4));
  const rest = Math.floor((CONTENT - first) / Math.max(n - 1, 1));
  const widths = [first, ...Array(n - 1).fill(rest)];
  widths[n - 1] += CONTENT - widths.reduce((a, b) => a + b, 0);
  const rows = block.rows.map((row, r) => new TableRow({
    cantSplit: true,
    children: row.cells.map((cell, i) => new TableCell({
      width: { size: widths[i], type: WidthType.DXA },
      verticalAlign: VerticalAlign.TOP,
      margins: { top: 50, bottom: 50, left: 0, right: 120 },
      borders: {
        top: row.total ? line(8, INK) : NONE, left: NONE, right: NONE,
        bottom: cell.header ? line(8, INK) : row.total ? NONE : line(4, RULE),
      },
      children: [new Paragraph({
        keepNext: r < block.rows.length - 1, // keeps the whole table on one page
        alignment: cell.num ? AlignmentType.RIGHT : AlignmentType.LEFT,
        children: [new TextRun({
          text: cell.text, font: SANS, size: 18, bold: cell.header || row.total || cell.hl,
          color: cell.header ? INK2 : cell.hl ? NAVY : INK,
        })],
      })],
    })),
  }));
  return [new Table({ width: { size: CONTENT, type: WidthType.DXA }, columnWidths: widths, rows }),
          new Paragraph({ spacing: { after: 120 }, children: [] })];
}

function keyfigs(block) {
  const n = block.items.length, w = Math.floor(CONTENT / n);
  const widths = Array(n).fill(w); widths[n - 1] += CONTENT - w * n;
  return [new Table({
    width: { size: CONTENT, type: WidthType.DXA }, columnWidths: widths,
    rows: [new TableRow({
      children: block.items.map((item, i) => new TableCell({
        width: { size: widths[i], type: WidthType.DXA },
        margins: { top: 140, bottom: 140, left: i ? 180 : 0, right: 140 },
        borders: { top: line(6, RULE), bottom: line(6, RULE), left: i ? line(6, RULE) : NONE, right: NONE },
        children: [
          new Paragraph({ children: [new TextRun({ text: item.value, font: SANS, size: 28, bold: true, color: NAVY })] }),
          new Paragraph({ children: [new TextRun({ text: item.label, font: SANS, size: 16, color: INK2 })] }),
        ],
      })),
    })],
  }), new Paragraph({ spacing: { after: 80 }, children: [] })];
}

function figure(block) {
  const maxW = 6.3 * 96; // inches of usable width at 96 px/in, as docx ImageRun expects pixels
  const scale = Math.min(1, maxW / block.width);
  return [
    new Paragraph({ keepNext: true, spacing: { before: 120, after: 80 },
      children: [new TextRun({ text: block.head, font: SANS, size: 19, bold: true, color: INK })] }),
    new Paragraph({ keepNext: true, spacing: { line: 240, lineRule: LineRuleType.AUTO, after: 0 }, children: [new ImageRun({
      type: "png", data: fs.readFileSync(block.image),
      transformation: { width: Math.round(block.width * scale), height: Math.round(block.height * scale) },
      altText: { title: block.head, description: block.caption.map((r) => r.text).join(""), name: block.head },
    })] }),
    new Paragraph({ spacing: { before: 60, after: 160 },
      children: textRuns(block.caption, { font: SANS, size: 17, color: INK2 }) }),
  ];
}

const children = [];
spec.blocks.forEach((b, i) => {
  const beforeTable = spec.blocks[i + 1] && spec.blocks[i + 1].type === "table";
  if (b.type === "h1") children.push(new Paragraph({ heading: HeadingLevel.TITLE, children: [new TextRun(b.text)] }));
  else if (b.type === "dek") children.push(new Paragraph({
    spacing: { after: 280 }, border: { bottom: { style: BorderStyle.SINGLE, size: 12, color: INK, space: 8 } },
    children: textRuns(b.runs, { font: SANS, size: 20, color: INK2 }) }));
  else if (b.type === "hook") children.push(new Paragraph({ spacing: { after: 160, line: 300, lineRule: LineRuleType.AUTO },
    children: textRuns(b.runs, { font: SANS, size: 30, bold: true, color: NAVY }) }));
  else if (b.type === "h2") children.push(new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun(b.text)] }));
  else if (b.type === "p") children.push(new Paragraph({ keepNext: beforeTable, children: textRuns(b.runs, b.note ? { size: 18, color: INK2 } : {}) }));
  else if (b.type === "bullets") for (const item of b.items) children.push(new Paragraph({
    numbering: { reference: "bullets", level: 0 }, spacing: { after: 60 },
    children: textRuns(item, b.note ? { size: 18, color: INK2 } : {}) }));
  else if (b.type === "table") children.push(...table(b));
  else if (b.type === "keyfigs") children.push(...keyfigs(b));
  else if (b.type === "figure") children.push(...figure(b));
});

const doc = new Document({
  title: spec.title, creator: "Initial Funding Automation",
  styles: {
    default: { document: { run: { font: SERIF, size: 20, color: INK }, paragraph: { spacing: { after: 110, line: 276, lineRule: LineRuleType.AUTO } } } },
    paragraphStyles: [
      { id: "Title", name: "Title", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { font: SANS, size: 40, bold: true, color: INK }, paragraph: { spacing: { after: 60 } } },
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { font: SANS, size: 25, bold: true, color: INK },
        paragraph: { spacing: { before: 300, after: 100 }, keepNext: true, outlineLevel: 0 } },
    ],
  },
  numbering: { config: [{ reference: "bullets", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•",
    alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 300, hanging: 220 } } } }] }] },
  sections: [{
    properties: { page: { size: { width: PAGE_W, height: 15840 }, margin: { top: 1200, bottom: 1250, left: MARGIN, right: MARGIN } } },
    footers: { default: new Footer({ children: [new Paragraph({
      tabStops: [{ type: TabStopType.RIGHT, position: CONTENT }],
      children: [
        new TextRun({ text: spec.title, font: SANS, size: 15, color: MUTED }),
        new TextRun({ children: ["\t", PageNumber.CURRENT, " of ", PageNumber.TOTAL_PAGES], font: SANS, size: 15, color: MUTED }),
      ] })] }) },
    children,
  }],
});

Packer.toBuffer(doc).then((buf) => fs.writeFileSync(spec.out, buf));
