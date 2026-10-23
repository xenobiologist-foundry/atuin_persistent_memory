use std::{env, fs, path::Path};

fn main() {
    // Compiled from the exact source used by the native dependency, not a guess
    // at a "latest" migration number. Checksum comparison happens read-only.
    let mut source = String::new();
    for (name, dir) in [("HISTORY", "migrations"), ("RECORD", "record-migrations"), ("META", "meta-migrations")] {
        let root = Path::new("../atuin-client").join(dir);
        let mut files: Vec<_> = fs::read_dir(&root).unwrap().map(|x| x.unwrap().path()).filter(|x| x.extension().is_some_and(|s| s == "sql")).collect();
        files.sort();
        source += &format!("const {name}: &[(i64, &[u8])] = &[\n");
        for file in files {
            let version: i64 = file.file_name().unwrap().to_str().unwrap().split('_').next().unwrap().parse().unwrap();
            let absolute = fs::canonicalize(&file).unwrap();
            source += &format!("({version}, include_bytes!({:?})),\n", absolute.to_str().unwrap());
            println!("cargo:rerun-if-changed={}", file.display());
        }
        source += "];\n";
    }
    fs::write(Path::new(&env::var("OUT_DIR").unwrap()).join("migrations.rs"), source).unwrap();
}
