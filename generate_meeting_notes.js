const { 
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  AlignmentType, BorderStyle, WidthType, ShadingType, LevelFormat,
  PageOrientation
} = require('docx');
const fs = require('fs');

const dataPath = process.argv[2];
const outputPath = process.argv[3];
if (!dataPath || !outputPath) {
  console.error('Usage: node generate_meeting_notes.js <data.json> <output.docx>');
  process.exit(1);
}

const data = JSON.parse(fs.readFileSync(dataPath, 'utf8'));
const { title, date_str, attendees_str, prepared_by, note, sections, action_items, transcript } = data;

// ── Helpers ────────────────────────────────────────────────────────────────────
const arial = (text, opts = {}) => new TextRun({
  text,
  font: 'Arial',
  size: opts.size || 20,
  bold: opts.bold || false,
  italics: opts.italics || false,
  color: opts.color || '000000',
});

const cellBorder = { style: BorderStyle.SINGLE, size: 1, color: 'CCCCCC' };
const cellBorders = { top: cellBorder, bottom: cellBorder, left: cellBorder, right: cellBorder };
const cellMargins = { top: 80, bottom: 80, left: 120, right: 120 };

function labelCell(text, width) {
  return new TableCell({
    width: { size: width, type: WidthType.DXA },
    borders: cellBorders,
    shading: { fill: '1F3864', type: ShadingType.CLEAR },
    margins: cellMargins,
    children: [new Paragraph({ children: [arial(text, { bold: true, color: 'FFFFFF' })] })],
  });
}

function valueCell(text, width) {
  return new TableCell({
    width: { size: width, type: WidthType.DXA },
    borders: cellBorders,
    shading: { fill: 'F2F2F2', type: ShadingType.CLEAR },
    margins: cellMargins,
    children: [new Paragraph({ children: [arial(text)] })],
  });
}

// ── Document ───────────────────────────────────────────────────────────────────
const children = [];

// Empty spacer para at top
children.push(new Paragraph({ spacing: { before: 80, after: 0 }, children: [new TextRun('')] }));

// Title
children.push(new Paragraph({
  spacing: { before: 160, after: 80 },
  children: [arial(`Meeting Notes  —  ${date_str}`, { bold: true, color: '1F3864', size: 32 })],
}));

// Info table (2 rows x 4 cols: [1800, 3780, 1200, 2580])
children.push(new Table({
  width: { size: 9360, type: WidthType.DXA },
  columnWidths: [1800, 3780, 1200, 2580],
  rows: [
    new TableRow({ children: [
      labelCell('Meeting', 1800),
      valueCell(title, 3780),
      labelCell('Date', 1200),
      valueCell(date_str, 2580),
    ]}),
    new TableRow({ children: [
      labelCell('Attendees', 1800),
      valueCell(attendees_str || 'See recording', 3780),
      labelCell('Prepared by', 1200),
      valueCell(prepared_by || 'Nate Fisher', 2580),
    ]}),
  ],
}));

// Spacer
children.push(new Paragraph({ spacing: { before: 200, after: 0 }, children: [new TextRun('')] }));

// Note callout (if present)
if (note && note.trim()) {
  children.push(new Paragraph({
    border: { left: { style: BorderStyle.SINGLE, color: 'BF8F00', size: 12, space: 4 } },
    shading: { fill: 'FFF2CC', type: ShadingType.CLEAR },
    spacing: { before: 0, after: 120 },
    indent: { left: 160 },
    children: [arial(`Note: ${note}`, { italics: true, color: '7F6000', size: 19 })],
  }));
  children.push(new Paragraph({ spacing: { before: 160, after: 0 }, children: [new TextRun('')] }));
}

// Section heading helper
function sectionHeading(text) {
  return new Paragraph({
    border: { bottom: { style: BorderStyle.SINGLE, color: '1F3864', size: 6, space: 1 } },
    spacing: { before: 240, after: 120 },
    children: [arial(text, { bold: true, color: '1F3864', size: 24 })],
  });
}

// Bullet helper
function bulletPara(text) {
  return new Paragraph({
    style: 'ListParagraph',
    numbering: { reference: 'bullets', level: 0 },
    spacing: { before: 40, after: 40 },
    children: [arial(text, { bold: false })],
  });
}

// Sections
for (const section of (sections || [])) {
  children.push(sectionHeading(section.title));
  children.push(new Paragraph({ spacing: { before: 80, after: 0 }, children: [new TextRun('')] }));
  for (const bullet of (section.bullets || [])) {
    children.push(bulletPara(bullet));
  }
  children.push(new Paragraph({ spacing: { before: 120, after: 0 }, children: [new TextRun('')] }));
}

// Action Items
if (action_items && action_items.length > 0) {
  children.push(sectionHeading('ACTION ITEMS SUMMARY'));
  children.push(new Paragraph({ spacing: { before: 100, after: 0 }, children: [new TextRun('')] }));

  const actionRows = [
    new TableRow({ children: [
      new TableCell({
        width: { size: 4200, type: WidthType.DXA }, borders: cellBorders,
        shading: { fill: '1F3864', type: ShadingType.CLEAR }, margins: cellMargins,
        children: [new Paragraph({ children: [arial('Action Item', { bold: true, color: 'FFFFFF' })] })],
      }),
      new TableCell({
        width: { size: 1800, type: WidthType.DXA }, borders: cellBorders,
        shading: { fill: '1F3864', type: ShadingType.CLEAR }, margins: cellMargins,
        children: [new Paragraph({ children: [arial('Owner', { bold: true, color: 'FFFFFF' })] })],
      }),
      new TableCell({
        width: { size: 3360, type: WidthType.DXA }, borders: cellBorders,
        shading: { fill: '1F3864', type: ShadingType.CLEAR }, margins: cellMargins,
        children: [new Paragraph({ children: [arial('Due / Status', { bold: true, color: 'FFFFFF' })] })],
      }),
    ]}),
  ];

  for (const item of action_items) {
    actionRows.push(new TableRow({ children: [
      new TableCell({
        width: { size: 4200, type: WidthType.DXA }, borders: cellBorders,
        shading: { fill: 'F2F2F2', type: ShadingType.CLEAR }, margins: cellMargins,
        children: [new Paragraph({ children: [arial(item.action || '')] })],
      }),
      new TableCell({
        width: { size: 1800, type: WidthType.DXA }, borders: cellBorders,
        shading: { fill: 'F2F2F2', type: ShadingType.CLEAR }, margins: cellMargins,
        children: [new Paragraph({ children: [arial(item.owner || 'TBD')] })],
      }),
      new TableCell({
        width: { size: 3360, type: WidthType.DXA }, borders: cellBorders,
        shading: { fill: 'F2F2F2', type: ShadingType.CLEAR }, margins: cellMargins,
        children: [new Paragraph({ children: [arial(item.due || 'TBD')] })],
      }),
    ]}));
  }

  children.push(new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: [4200, 1800, 3360],
    rows: actionRows,
  }));
}

// Full Transcript (if present)
if (transcript && transcript.length > 0) {
  children.push(new Paragraph({ spacing: { before: 240, after: 0 }, children: [new TextRun('')] }));
  children.push(sectionHeading('FULL TRANSCRIPT'));
  let currentSpeaker = null;
  for (const u of transcript) {
    const speaker = u.speaker || 'Unknown';
    const text = (u.text || '').trim();
    if (!text) continue;
    if (speaker !== currentSpeaker) {
      children.push(new Paragraph({
        spacing: { before: 40, after: 0 },
        children: [
          arial(speaker + ': ', { bold: true, size: 18 }),
          arial(text, { size: 18 }),
        ],
      }));
      currentSpeaker = speaker;
    } else {
      // Append to a new run in new paragraph (simplified)
      children.push(new Paragraph({
        spacing: { before: 0, after: 0 },
        children: [arial(text, { size: 18 })],
      }));
    }
  }
}

// ── Build doc ──────────────────────────────────────────────────────────────────
const doc = new Document({
  numbering: {
    config: [{
      reference: 'bullets',
      levels: [{
        level: 0,
        format: LevelFormat.BULLET,
        text: '\u25CF',
        alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: 720, hanging: 360 } } },
      }],
    }],
  },
  styles: {
    default: { document: { run: { font: 'Arial', size: 20 } } },
    paragraphStyles: [{
      id: 'ListParagraph',
      name: 'List Paragraph',
      basedOn: 'Normal',
      quickFormat: true,
      run: { font: 'Arial', size: 20 },
    }],
  },
  sections: [{
    properties: {
      page: {
        size: { width: 12240, height: 15840, orientation: PageOrientation.PORTRAIT },
        margin: { top: 1080, right: 1080, bottom: 1080, left: 1080 },
      },
    },
    children,
  }],
});

Packer.toBuffer(doc).then(buffer => {
  fs.writeFileSync(outputPath, buffer);
  console.log('OK:' + outputPath);
}).catch(err => {
  console.error('ERROR:' + err.message);
  process.exit(1);
});
