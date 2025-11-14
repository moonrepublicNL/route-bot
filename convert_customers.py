import sys, re, csv, pathlib

def norm_pc(pc):
    if not pc: return ""
    s = re.sub(r"\s+","",str(pc).upper())
    m = re.match(r"^(\d{4})([A-Z]{2})$", s)
    if m: return f"{m.group(1)} {m.group(2)}"
    m = re.search(r"(\d{4})\s*([A-Z]{2})", s)
    return f"{m.group(1)} {m.group(2)}" if m else ""

def autodialect(p):
    with open(p,'r',newline='',encoding='utf-8',errors='ignore') as f:
        sample = f.read(4096)
    for d in [',',';','\t']:
        if d in sample: return d
    return ','

def main(inp, outp):
    delim = autodialect(inp)
    with open(inp,'r',newline='',encoding='utf-8',errors='ignore') as f:
        r = csv.DictReader(f, delimiter=delim)
        cols = {c.lower():c for c in r.fieldnames}
        def pick(*names):
            for n in names:
                if n in cols: return cols[n]
            return None
        c_name = pick('name','account name','naam','bedrijf','klant')
        c_addr = pick('address','adres','straat','street')
        c_nr   = pick('nr','huisnummer','number','no')
        c_pc   = pick('postcode','zip','postal code')
        c_city = pick('city','stad','plaats','town')

        with open(outp,'w',newline='',encoding='utf-8') as g:
            w = csv.writer(g)
            w.writerow(['Name','FullAddress','Latitude','Longitude'])
            for row in r:
                name = row[c_name].strip() if c_name else ''
                addr = (row[c_addr].strip() if c_addr else '')
                nr   = (row[c_nr].strip() if c_nr else '')
                pc   = norm_pc(row[c_pc] if c_pc else '')
                city = (row[c_city].strip() if c_city else 'Amsterdam')
                base = (addr + (' ' + nr if nr else '')).strip()
                parts = [p for p in [base, pc, city, 'NL'] if p]
                full = ', '.join(parts)
                w.writerow([name, full, '', ''])

if __name__ == '__main__':
    if len(sys.argv)<3:
        print("Gebruik: python3 convert_customers.py <input.csv> <output.csv>")
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])
