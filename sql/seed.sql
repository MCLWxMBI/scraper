-- Source: https://github.com/MCLWxMBI/website/blob/main/seed.sql
-- Upstream blob: 7c97d041ef7e00ab149c3464dfb52a8504b849e2
-- Local catalogue: GWMWater past projects removed; IDs renumbered 1–41.
-- Gippsland uses future projects, Wannon in-planning, Western Port current projects.
-- Barwon Water, VEWH and AEMC remain inactive. The runner owns the transaction.
-- Return the expected values independently of INSERT RETURNING so verification
-- also detects changes made by database triggers.
WITH seed (id, name, index_url, active, notes) AS (
  VALUES
  (1, 'Legislative Assembly Environment and Planning Committee', 'https://www.parliament.vic.gov.au/epc-la', TRUE, NULL),
  (2, 'Legislative Council Environment and Planning Committee', 'https://www.parliament.vic.gov.au/epc-lc', TRUE, NULL),
  (3, 'Scrutiny of Acts and Regulations Committee', 'https://www.parliament.vic.gov.au/sarc', TRUE, 'Only include legislation that fits into an environment-related category of interest.'),
  (4, 'Melbourne Water', 'https://letstalk.melbournewater.com.au/projects', TRUE, NULL),
  (5, 'Great Western Water', 'https://www.gww.com.au/faults-works/upgrades-projects/planned-works-projects', TRUE, NULL),
  (6, 'South East Water', 'https://southeastwater.com.au/faults-and-works/works/projects', TRUE, NULL),
  (7, 'Yarra Valley Water', 'https://engage.yvw.com.au/projects', TRUE, NULL),
  (8, 'Barwon Water', 'https://www.barwonwater.vic.gov.au/about-us/major-projects', FALSE, 'Unable to access.'),
  (9, 'Coliban Water', 'https://connect.coliban.com.au/projects', TRUE, NULL),
  (10, 'East Gippsland Water', 'https://egwater.vic.gov.au/community/news', TRUE, 'News page rather than a dedicated projects index; determine which news items relate to projects.'),
  (11, 'Goulburn Valley Water', 'https://www.gvwater.vic.gov.au/projects', TRUE, NULL),
  (12, 'Gippsland Water', 'https://www.gippswater.com.au/outages-works-and-projects/major-projects/future-major-projects', TRUE, NULL),
  (13, 'Grampians Wimmera Mallee Water - Current Projects', 'https://gwmwater.org.au/building-and-development/projects/current-projects/', TRUE, NULL),
  (14, 'Lower Murray Water', 'https://yoursay.lmw.vic.gov.au/projects', TRUE, NULL),
  (15, 'North East Water', 'https://haveyoursay.newater.com.au/projects', TRUE, NULL),
  (16, 'South Gippsland Water', 'https://www.sgwater.com.au/projects', TRUE, NULL),
  (17, 'Wannon Water', 'https://www.wannonwater.com.au/community-and-environment/projects-and-initiatives?filter_project_status%5B%5D=223', TRUE, NULL),
  (18, 'Western Port Water', 'https://www.westernportwater.com.au/our-community/current-projects', TRUE, NULL),
  (19, 'Southern Rural Water', 'https://www.srw.com.au/initiatives/projects', TRUE, NULL),
  (20, 'Goulburn-Murray Water', 'https://g-mwater.com.au/customer-services-resources/projects', TRUE, NULL),
  (21, 'Essential Services Commission', 'https://www.esc.vic.gov.au/current-consultations', TRUE, NULL),
  (22, 'Engage Victoria', 'https://engage.vic.gov.au/project', TRUE, NULL),
  (23, 'Senate Environment and Communications', 'https://www.aph.gov.au/Parliamentary_Business/Committees/Senate/Environment_and_Communications', TRUE, NULL),
  (24, 'Senate Rural and Regional Affairs and Transport', 'https://www.aph.gov.au/Parliamentary_Business/Committees/Senate/Rural_and_Regional_Affairs_and_Transport', TRUE, NULL),
  (25, 'House Climate Change, Energy, Environment and Water', 'https://www.aph.gov.au/Parliamentary_Business/Committees/House/Climate_Change_Energy_Environment_and_Water', TRUE, NULL),
  (26, 'House Industry, Innovation and Science', 'https://www.aph.gov.au/Parliamentary_Business/Committees/House/Industry_Innovation_and_Science', TRUE, NULL),
  (27, 'House Regional Development, Infrastructure and Transport', 'https://www.aph.gov.au/Parliamentary_Business/Committees/House/Regional_Development_Infrastructure_and_Transport', TRUE, NULL),
  (28, 'House Primary Industries', 'https://www.aph.gov.au/Parliamentary_Business/Committees/House/Primary_Industries', TRUE, NULL),
  (29, 'Joint Aboriginal and Torres Strait Islander Affairs', 'https://www.aph.gov.au/Parliamentary_Business/Committees/Joint/Aboriginal_and_Torres_Strait_Islander_Affairs', TRUE, NULL),
  (30, 'Joint Treaties', 'https://www.aph.gov.au/Parliamentary_Business/Committees/Joint/Treaties', TRUE, 'Only include environment-related treaties.'),
  (31, 'Joint Northern Australia', 'https://www.aph.gov.au/Parliamentary_Business/Committees/Joint/Northern_Australia', TRUE, NULL),
  (32, 'Department of Industry, Science and Resources', 'https://consult.industry.gov.au/', TRUE, NULL),
  (33, 'Productivity Commission', 'https://www.pc.gov.au/inquiries-and-research/', TRUE, NULL),
  (34, 'Climate Change Authority', 'https://consult.climatechangeauthority.gov.au/find-consultations', TRUE, NULL),
  (35, 'Australian Energy Market Commission', 'https://www.aemc.gov.au/news-centre/submissions-to-inquiries', FALSE, 'Unable to access; HTTP 403 during traversal audit.'),
  (36, 'Department of Climate Change, Energy, the Environment and Water', 'https://consult.dcceew.gov.au/find-consultations', TRUE, NULL),
  (37, 'Clean Energy Regulator', 'https://cer.gov.au/news-and-media/public-consultations', TRUE, NULL),
  (38, 'Department of Infrastructure, Transport, Regional Development, Communications, Sport and the Arts', 'https://www.infrastructure.gov.au/have-your-say', TRUE, NULL)
), upserted AS (
  INSERT INTO public.website_indexes (id, name, index_url, active, notes)
  SELECT id, name, index_url, active, notes FROM seed
  ON CONFLICT (id) DO UPDATE SET
    name = EXCLUDED.name,
    index_url = EXCLUDED.index_url,
    active = EXCLUDED.active,
    notes = EXCLUDED.notes
  RETURNING id
)
SELECT id, name, index_url, active, notes FROM seed ORDER BY id;

-- Category choices for opportunity classification. Caller owns the transaction.
INSERT INTO public.categories (name) VALUES
    ('Biodiversity & ecosystems'),
    ('Climate change'),
    ('First Nations & cultural heritage'),
    ('Water & resources'),
    ('Communities & environment')
ON CONFLICT (name) DO NOTHING;
