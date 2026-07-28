import { createContext, useContext, useEffect, useState } from "react";
import { api } from "@/lib/api";

const ProjectContext = createContext(null);

export function ProjectProvider({ children }) {
  const [projects, setProjects] = useState([]);
  const [current, setCurrent] = useState(null);
  const [loading, setLoading] = useState(true);

  const refresh = async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/projects");
      setProjects(data);
      const savedId = localStorage.getItem("mm_project_id");
      const found = data.find((p) => p.id === savedId) || data[0] || null;
      setCurrent(found);
      if (found) localStorage.setItem("mm_project_id", found.id);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { refresh(); }, []);

  const select = (p) => {
    setCurrent(p);
    if (p) localStorage.setItem("mm_project_id", p.id);
    else localStorage.removeItem("mm_project_id");
  };

  return (
    <ProjectContext.Provider value={{ projects, current, select, refresh, loading }}>
      {children}
    </ProjectContext.Provider>
  );
}

export const useProject = () => useContext(ProjectContext);
