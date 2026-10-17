import { circuitStudies } from '../lib/circuit-studies.ts';
/** Plain-text content only: no executable HTML is accepted by the CMS. */
export type Project = {
  slug: string;
  title: string;
  category: string;
  status: string;
  summary: string;
  image: string;
  imageAlt: string;
  tools: string;
  evidenceUrl: string;
  sourceUrl: string;
  demoUrl: string;
  sections: {
    heading: string;
    text: string;
    image: string;
    imageAlt: string;
  }[];
};
export type Section = {
  id: string;
  type: string;
  visible: string;
  label: string;
  heading: string;
  text: string;
  image: string;
  imageAlt: string;
  buttonLabel: string;
  buttonUrl: string;
  layout: string;
};
export type Design = {
  colors: {
    paper: string;
    ink: string;
    muted: string;
    surface: string;
    line: string;
    accent: string;
    buttonText: string;
  };
  typography: string;
  spacing: string;
  radius: string;
  width: string;
  heroLayout: string;
  projectLayout: string;
  sections: Section[];
};
export type Content = {
  design: Design;
  profile: {
    brand: string;
    fullName: string;
    alternateName: string;
    role: string;
    headline: string;
    introduction: string;
    location: string;
    portrait: string;
    portraitAlt: string;
    cv: string;
    about: string;
    email: string;
    phone: string;
    github: string;
    linkedin: string;
    contactHeading: string;
    contactText: string;
  };
  seo: {
    title: string;
    description: string;
    image: string;
  };
  capabilities: {
    title: string;
    text: string;
  }[];
  skills: {
    title: string;
    text: string;
  }[];
  experience: {
    role: string;
    company: string;
    period: string;
    summary: string;
  }[];
  projects: Project[];
  circuits: Project[];
};
export const initialContent: Content = {
  design: {
    colors: {
      paper: '#f7f7f2',
      ink: '#172d32',
      muted: '#516569',
      surface: '#edf0e8',
      line: '#bcc9bd',
      accent: '#c3df75',
      buttonText: '#ffffff'
    },
    typography: 'modern',
    spacing: '72',
    radius: '10',
    width: '1200',
    heroLayout: 'split',
    projectLayout: 'rows',
    sections: [{
      id: 'hero',
      type: 'hero',
      visible: 'yes',
      label: 'Introduction',
      heading: '',
      text: '',
      image: '',
      imageAlt: '',
      buttonLabel: '',
      buttonUrl: '',
      layout: 'text'
    }, {
      id: 'projects',
      type: 'projects',
      visible: 'yes',
      label: 'Selected work',
      heading: 'Selected engineering projects.',
      text: 'Selected projects, their implementation and the evidence behind them.',
      image: '',
      imageAlt: '',
      buttonLabel: '',
      buttonUrl: '',
      layout: 'text'
    }, {
      id: 'what-i-build',
      type: 'capabilities',
      visible: 'yes',
      label: 'What I build',
      heading: 'Hardware. Software. The connection between them.',
      text: '',
      image: '',
      imageAlt: '',
      buttonLabel: '',
      buttonUrl: '',
      layout: 'text'
    }, {
      id: 'circuits',
      type: 'circuits',
      visible: 'yes',
      label: 'On the workbench',
      heading: 'Circuit design & simulation.',
      text: 'Schematics, design decisions and the limitations that still need testing.',
      image: '',
      imageAlt: '',
      buttonLabel: '',
      buttonUrl: '',
      layout: 'text'
    }, {
      id: 'experience',
      type: 'experience',
      visible: 'yes',
      label: 'Experience',
      heading: 'Engineering experience.',
      text: '',
      image: '',
      imageAlt: '',
      buttonLabel: '',
      buttonUrl: '',
      layout: 'text'
    }, {
      id: 'about',
      type: 'about',
      visible: 'yes',
      label: 'About & skills',
      heading: 'Across disciplines. Grounded in engineering.',
      text: '',
      image: '',
      imageAlt: '',
      buttonLabel: '',
      buttonUrl: '',
      layout: 'text'
    }, {
      id: 'contact',
      type: 'contact',
      visible: 'yes',
      label: 'Start a conversation',
      heading: '',
      text: '',
      image: '',
      imageAlt: '',
      buttonLabel: '',
      buttonUrl: '',
      layout: 'text'
    }]
  },
  profile: {
    brand: 'Elijah Peters',
    fullName: 'Peters Elijah Temidayo',
    alternateName: 'Elijah Peters',
    role: 'Electrical & Electronics Engineer',
    headline: 'Engineering from circuit to software.',
    introduction: 'I design electronic circuits, develop embedded systems, and apply machine learning to engineering problems. My work spans circuit simulation, PCB design, intelligent automation, and predictive software.',
    location: 'Ogun State, Nigeria',
    portrait: '/assets/elijah-portrait-2026.png',
    portraitAlt: 'Peters Elijah Temidayo, professionally known as Elijah Peters, wearing a navy suit and tie',
    cv: '/assets/Peters-Elijah-CV.pdf',
    about: 'I am an Electrical & Electronics Engineer with a B.Eng from Olabisi Onabanjo University (Second Class Upper). My work connects circuit design and power electronics with embedded systems, hardware/software integration and applied machine learning. I also review circuit designs and AI-generated engineering work for technical accuracy.',
    email: 'peterselijah11@gmail.com',
    phone: '+2349021985375',
    github: 'https://github.com/Elijahpeters',
    linkedin: 'https://www.linkedin.com/in/elijahpeters01',
    contactHeading: 'Have an engineering problem in mind?',
    contactText: 'I’m open to electronics, embedded systems, AI evaluation and multidisciplinary engineering opportunities.'
  },
  seo: {
    title: 'Peters Elijah Temidayo (Elijah Peters) | Electrical & Electronics Engineer',
    description: 'Portfolio of Peters Elijah Temidayo (Elijah Peters), an Electrical & Electronics Engineer focused on embedded systems, circuit/PCB design and applied AI/ML.',
    image: '/assets/elijah-portrait-2026.png'
  },
  capabilities: [{
    title: 'Circuits & PCB development',
    text: 'Analogue circuits, power-stage studies and PCB layouts, supported by simulation and design checks.'
  }, {
    title: 'Embedded systems',
    text: 'Sensor interfaces, control logic and hardware–software integration for intelligent automation.'
  }, {
    title: 'Applied AI & machine learning',
    text: 'Computer vision and predictive software, with explicit evaluation methods and limitations.'
  }],
  skills: [{
    title: 'Electronics & simulation',
    text: 'LTspice, KiCad, Qucs-S, DesignSpark PCB, Proteus, MATLAB/Simulink'
  }, {
    title: 'AI & data',
    text: 'Python, OpenCV, MediaPipe, DeepFace, scikit-learn, Pandas, NumPy'
  }, {
    title: 'Embedded & software',
    text: 'Arduino, C++, SQL, HTML/CSS, Bash, hardware/software integration'
  }],
  experience: [{
    role: 'Electronics Circuit Design Expert',
    company: 'Micro1',
    period: 'From May 2026 · Project work',
    summary: 'Reviewing schematics, PCB layouts, netlists and AI-generated engineering outputs for technical accuracy.'
  }, {
    role: 'AI Technical Trainer & Data Specialist',
    company: 'Micro1',
    period: 'Nov 2025 – Feb 2026',
    summary: 'Built and reviewed technical datasets, focusing on edge cases, executable reasoning and evaluation reliability.'
  }, {
    role: 'Data Science Intern',
    company: 'Codsoft',
    period: 'Aug – Sep 2024',
    summary: 'Applied data preparation, exploratory analysis, feature engineering and model evaluation.'
  }, {
    role: 'Data Science Intern',
    company: 'DSN-OOU',
    period: 'Mar – May 2024',
    summary: 'Applied Python analysis and machine-learning methods in a collaborative, project-based internship.'
  }],
  circuits: circuitStudies.map(study => ({
    slug: study.id,
    title: study.title,
    category: study.type,
    status: study.result,
    summary: study.description,
    image: study.image,
    imageAlt: study.alt,
    tools: 'Circuit design & simulation',
    evidenceUrl: study.href,
    sourceUrl: '',
    demoUrl: '',
    sections: [{
      image: '',
      imageAlt: '',
      heading: 'Purpose',
      text: study.purpose
    }, {
      image: '',
      imageAlt: '',
      heading: 'Approach',
      text: study.approach
    }, {
      image: '',
      imageAlt: '',
      heading: 'Evidence',
      text: study.evidence
    }, {
      image: '',
      imageAlt: '',
      heading: 'Limitations',
      text: study.limitation
    }, {
      image: '',
      imageAlt: '',
      heading: 'Next check',
      text: study.nextCheck
    }]
  })),
  projects: [{
    slug: 'aurapass',
    title: 'AuraPass',
    category: 'Computer vision / Embedded systems',
    status: 'Offline prototype · simulated gate',
    summary: 'Biometric examination access combining computer vision, student eligibility, seat allocation and simulated gate control.',
    image: '/assets/aurapass-proteus.png',
    imageAlt: 'AuraPass gate-control circuit in Proteus',
    tools: 'Python / OpenCV / SQLite / Proteus',
    evidenceUrl: '/projects/aurapass',
    sourceUrl: 'https://github.com/Elijahpeters/AuraPass',
    demoUrl: '',
    sections: [{
      image: '',
      imageAlt: '',
      heading: 'The engineering problem',
      text: 'Connect identity verification and examination eligibility with a controlled access decision and a seat assignment.'
    }, {
      image: '',
      imageAlt: '',
      heading: 'Implementation & evidence',
      text: 'The offline prototype integrates the software workflow with simulated gate control. The original case study retains the flowchart, interface screenshots, evaluation evidence and technical limitations.'
    }, {
      image: '',
      imageAlt: '',
      heading: 'Current status',
      text: 'This is a prototype with simulated gate hardware. It is not presented as a deployed examination-security system.'
    }]
  }, {
    slug: 'skyeta',
    title: 'SkyETA',
    category: 'Applied machine learning / Software',
    status: 'Application · limited model coverage',
    summary: 'Flight intelligence connecting fare search, flight-data analysis and machine-learning delay estimates.',
    image: '/assets/skyeta-logo-clean.png',
    imageAlt: 'SkyETA flight-intelligence application logo',
    tools: 'Python / LightGBM / TypeScript / React',
    evidenceUrl: '/projects/skyeta',
    sourceUrl: 'https://github.com/Elijahpeters/peters-elijah-portfolio',
    demoUrl: '/skyeta',
    sections: [{
      image: '',
      imageAlt: '',
      heading: 'Purpose',
      text: 'Bring fare-search functionality and flight analysis into one application, with provider data and model estimates clearly distinguished.'
    }, {
      image: '',
      imageAlt: '',
      heading: 'Model coverage',
      text: 'Trained delay estimates cover verified U.S. routes. Coverage and provider availability are limited; predictions are estimates, not guarantees.'
    }, {
      image: '',
      imageAlt: '',
      heading: 'Explore the work',
      text: 'The original technical case study documents the implementation, evaluation and known limitations. The application remains available separately.'
    }]
  }, {
    slug: 'incubator-carrier',
    title: 'Incubator Carrier PCB',
    category: 'PCB development / Control systems',
    status: 'Design checks passed · not bench-tested',
    summary: 'A two-layer interface board for an Arduino Mega incubator controller, connecting sensors, relay-control signals and status indicators.',
    image: '/assets/incubator-pcb-angled.png',
    imageAlt: 'KiCad 3D render of the incubator carrier PCB, not assembled hardware',
    tools: 'KiCad / 2 layers / 96 × 76 mm / Rev C',
    evidenceUrl: '/projects/incubator-carrier',
    sourceUrl: '',
    demoUrl: '',
    sections: [{
      image: '',
      imageAlt: '',
      heading: 'Design intent',
      text: 'Organise the connections between the controller, sensors, relay-control signals and indicators in an incubator control system.'
    }, {
      image: '',
      imageAlt: '',
      heading: 'Design evidence',
      text: 'The retained technical case study includes the schematic, PCB layout, pin-map audit and saved ERC/DRC results.'
    }, {
      image: '',
      imageAlt: '',
      heading: 'Validation boundary',
      text: 'The design has passed its recorded design checks. The PCB has not been physically bench-tested; the images are KiCad renders and design evidence.'
    }]
  }]
};
const MAX_STRING = 12000;
export function safeUrl(value: string, optional = false): boolean {
  if (!value) return optional;
  if (value.startsWith('/') && !value.startsWith('//') && !/[\\\s]/.test(value)) return true;
  try {
    const u = new URL(value);
    return u.protocol === 'https:' && !u.username && !u.password;
  } catch {
    return false;
  }
}
/** Closed schema, bounded arrays, safe URLs and unique stable slugs. */
export function validateContent(value: unknown): Content {
  const walk = (sample: unknown, v: unknown, path: string): void => {
    if (typeof sample === 'string') {
      if (typeof v !== 'string' || v.length > MAX_STRING) throw new Error(`${path}: expected text up to ${MAX_STRING} characters`);
      return;
    }
    if (Array.isArray(sample)) {
      if (!Array.isArray(v) || v.length > 40) throw new Error(`${path}: expected a list of up to 40 items`);
      v.forEach((item, i) => walk(sample[0], item, `${path}.${i}`));
      return;
    }
    if (!v || typeof v !== 'object' || Array.isArray(v)) throw new Error(`${path}: expected an object`);
    const keys = Object.keys(sample as object);
    if (Object.keys(v).some(k => !keys.includes(k))) throw new Error(`${path}: unknown field`);
    keys.forEach(k => walk((sample as Record<string, unknown>)[k], (v as Record<string, unknown>)[k], `${path}.${k}`));
  };
  walk(initialContent, value, 'content');
  const c = value as Content;
  for (const key of ['fullName', 'alternateName', 'brand', 'role', 'headline', 'introduction'] as const) if (!c.profile[key].trim()) throw new Error(`${key} is required`);
  if (!c.seo.title.trim() || !c.seo.description.trim()) throw new Error('SEO title and description are required');
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(c.profile.email)) throw new Error('Enter a valid contact email');
  for (const u of [c.profile.portrait, c.profile.cv, c.profile.github, c.profile.linkedin, c.seo.image]) if (!safeUrl(u)) throw new Error('Use an HTTPS URL or an absolute local path');
  const seen = new Set<string>();
  for (const p of [...c.projects, ...c.circuits]) {
    if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(p.slug) || seen.has(p.slug)) throw new Error('Projects need unique lowercase, hyphen-separated slugs');
    seen.add(p.slug);
    if (!p.title.trim() || !p.summary.trim()) throw new Error('Project title and summary are required');
    for (const section of p.sections) if (!safeUrl(section.image, true)) throw new Error('Unsafe evidence image URL');
    for (const u of [p.image, p.evidenceUrl, p.sourceUrl, p.demoUrl]) if (!safeUrl(u, true)) throw new Error('Unsafe project URL');
  }
  const d = c.design;
  if (!['modern', 'editorial', 'technical'].includes(d.typography) || !['split', 'portrait-left', 'stacked', 'text-only'].includes(d.heroLayout) || !['rows', 'cards'].includes(d.projectLayout)) throw new Error('Invalid design choice');
  for (const [v, min, max] of [[d.spacing, 32, 104], [d.radius, 0, 32], [d.width, 960, 1440]] as const) if (!/^\d+$/.test(v) || +v < min || +v > max) throw new Error('Invalid design range');
  for (const color of Object.values(d.colors)) if (!/^#[0-9a-fA-F]{6}$/.test(color)) throw new Error('Invalid colour: use six-digit hex');
  if (contrast(d.colors.ink, d.colors.paper) < 4.5 || contrast(d.colors.muted, d.colors.paper) < 4.5 || contrast(d.colors.ink, d.colors.surface) < 4.5 || contrast(d.colors.muted, d.colors.surface) < 4.5 || contrast(d.colors.ink, d.colors.buttonText) < 4.5 || contrast(d.colors.ink, d.colors.accent) < 4.5) throw new Error('Colour contrast is too low. Choose a darker text or lighter background colour.');
  const ids = new Set<string>();
  const types = new Set<string>();
  for (const section of d.sections) {
    if (!/^[a-z][a-z0-9-]*$/.test(section.id) || ids.has(section.id)) throw new Error('Sections need unique lowercase addresses');
    ids.add(section.id);
    const standardIds: Record<string, string> = {
      hero: 'hero',
      capabilities: 'what-i-build',
      projects: 'projects',
      circuits: 'circuits',
      experience: 'experience',
      about: 'about',
      contact: 'contact'
    };
    if (section.type !== 'custom' && standardIds[section.type] !== section.id) throw new Error('Standard section addresses must remain stable');
    if (!['hero', 'capabilities', 'projects', 'circuits', 'experience', 'about', 'contact', 'custom'].includes(section.type) || !['yes', 'no'].includes(section.visible) || !['text', 'image-left', 'image-right', 'callout'].includes(section.layout)) throw new Error('Invalid section choice');
    if (section.type !== 'custom') {
      if (types.has(section.type)) throw new Error('Only one of each standard section is allowed');
      types.add(section.type);
    }
    if (!safeUrl(section.image, true) || !safeUrl(section.buttonUrl, true)) throw new Error('Unsafe section URL');
  }
  if (!d.sections.some(s => s.type === 'hero' && s.visible === 'yes')) throw new Error('The introduction must remain visible');
  return c;
}
export function contrast(a: string, b: string) {
  const luminance = (hex: string) => {
    const rgb = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16) / 255).map(v => v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4);
    return rgb[0] * .2126 + rgb[1] * .7152 + rgb[2] * .0722;
  };
  const x = luminance(a),
    y = luminance(b);
  return (Math.max(x, y) + .05) / (Math.min(x, y) + .05);
}
