import numpy as np
from errors import MonotoneError, MonotoneBoundsError, ScoreCreationError

def create(reference_set_dict, monotone_relationship, minval=None, maxval=None):
  return HiScoreEngine(reference_set_dict, monotone_relationship, minval, maxval)

class HiScoreEngine:
  def __init__(self,reference_set_dict, monotone_relationship, minval, maxval):
    np_input = np.array(reference_set_dict.keys())
    self.monorel = np.array(monotone_relationship)
    self.bounds = zip(np.amin(np_input, axis=0),np.amax(np_input, axis=0))
    self.scale = self.monorel*(np.amax(np_input, axis=0)-np.amin(np_input, axis=0))
    self.points = {}
    for (p,v) in reference_set_dict.iteritems():
      key = np.array(p)/self.scale
      self.points[tuple(key.tolist())]=v
    if minval is not None:
      self.minval = float(minval)
    else:
      self.minval = None
    if maxval is not None:
      self.maxval = float(maxval)
    else:
      self.maxval = None
    self.__check_monotonicity__()
    if not (minval is None and maxval is None):
      self.__check_bounds__()

    self.dim = len(monotone_relationship)
    plus_vals, minus_vals = self.__solve__()
    self.point_objs = []
    for ((p,v),plusv,minusv) in zip(self.points.iteritems(), plus_vals, minus_vals):
      sp,ip = zip(*plusv)
      sm,im = zip(*minusv)
      self.point_objs.append(self.Point(p,v,sp,sm,ip,im))

  def __solve__(self):
    import gurobipy as grb
    
    model = grb.Model()
    model.setParam('OutputFlag',0)
    model.setParam('OptimalityTol',1e-6)
    model.setParam('IntFeasTol',1e-8)
    model.setParam('MIPGap',1e-8)
    model.setParam('MIPGapAbs',1e-8)
    model.update()
    
    # Cones on the plus and minus side
    lbs = [0 for p in self.monorel]
    ubs = [grb.GRB.INFINITY for p in self.monorel]
    sup_plus_vars = [[model.addVar(lb,ub) for (lb,ub) in zip(lbs,ubs)] for i in self.points]
    inf_plus_vars = [[model.addVar(lb,ub) for (lb,ub) in zip(lbs,ubs)] for i in self.points]
    sup_minus_vars = [[model.addVar(lb,ub) for (lb,ub) in zip(lbs,ubs)] for i in self.points]
    inf_minus_vars = [[model.addVar(lb,ub) for (lb,ub) in zip(lbs,ubs)] for i in self.points]
    model.update()

    # inf/sup relational constraints
    for (supv,infv) in zip(sup_plus_vars,inf_plus_vars):
      for (s,i) in zip(supv,infv):
        model.addConstr(s, grb.GRB.GREATER_EQUAL, i)
    for (supv,infv) in zip(sup_minus_vars,inf_minus_vars):
      for (s,i) in zip(supv,infv):
        model.addConstr(s, grb.GRB.LESS_EQUAL, i)

    # Upper cone constraints
    for (i,(pone,vone)) in enumerate(self.points.iteritems()):
      for (j,(ptwo,vtwo)) in enumerate(self.points.iteritems()):
        if i==j: continue
        lhs_sup = grb.LinExpr()
        lhs_inf = grb.LinExpr()
        for (di,(poned,ptwod)) in enumerate(zip(pone,ptwo)):
          run = ptwod - poned
          if ptwod > poned:
            supvar = sup_plus_vars[i][di]
            infvar = inf_plus_vars[i][di]
          elif ptwod < poned:
            supvar = sup_minus_vars[i][di]
            infvar = inf_minus_vars[i][di]
          lhs_sup += run*supvar
          lhs_inf += run*infvar
        model.addConstr(lhs_sup, grb.GRB.GREATER_EQUAL, vtwo-vone)
        model.addConstr(lhs_inf, grb.GRB.LESS_EQUAL, vtwo-vone)

    model.update()
    
    opt = grb.QuadExpr()
    for (supvdim,infvdim) in zip(sup_plus_vars,inf_plus_vars):
      for (supv,infv) in zip(supvdim,infvdim):
        opt += (supv - infv)*(supv-infv)
    for (supvdim,infvdim) in zip(sup_minus_vars,inf_minus_vars):
      for (supv,infv) in zip(supvdim,infvdim):
        opt += (infv-supv)*(infv-supv)
    model.setObjective(opt, grb.GRB.MINIMIZE)
    model.update()

    # Run it!
    model.optimize()
    # Post-mortem...
    if model.status != grb.GRB.OPTIMAL:
      if model.status == grb.GRB.INFEASIBLE or model.status == grb.GRB.INF_OR_UNBD:
        raise ScoreCreationError("Infeasible model")
      else:
        raise ScoreCreationError("Model not optimal!")
      return None
    # Pull out the coefficients from the variables
    plus_vars = [[(supv.x,infv.x) for (supv,infv) in zip(s,i)] for (s,i) in zip(sup_plus_vars,inf_plus_vars)]
    minus_vars = [[(supv.x,infv.x) for (supv,infv) in zip(s,i)] for (s,i) in zip(sup_minus_vars,inf_minus_vars)]
    return plus_vars, minus_vars

  def __monotone_rel__(self,a,b):
    # returns 1 if a > b, -1 if a < b, 0 otherwise
    # Assumes self.scale adjustment has already been made
    adj_diff = np.array(a)-np.array(b)
    if min(adj_diff) >= 0 and max(adj_diff) > 0:
      return 1
    elif max(adj_diff) > 0 and min(adj_diff) < 0:
      return 0
    else:
      return -1

  def __check_monotonicity__(self):
    for (x,v) in self.points.iteritems():
      points_greater_than = filter(lambda point: x==point or self.__monotone_rel__(point,x)==1, self.points.keys())
      for gt in points_greater_than:
        if self.points[gt] < v:
          raise MonotoneError(np.array(gt)*self.scale,self.points[gt],np.array(x)*self.scale,v)
      points_less_than = filter(lambda point: x==point or self.__monotone_rel__(x,point)==1, self.points.keys())
      for lt in points_less_than:
        if self.points[lt] > v:
          raise MonotoneError(np.array(lt)*self.scale,self.points[lt],np.array(x)*self.scale,v)

  def __check_bounds__(self):
    maxtest = 1e47 if self.maxval is None else self.maxval
    mintest = -1e47 if self.minval is None else self.minval
    for (x,v) in self.points.iteritems():
      if v > maxtest:
        raise MonotoneBoundsError(x,v,self.maxval,"maximum")
      if v < mintest:
        raise MonotoneBoundsError(x,v,self.minval,"minimum")

  class Point:
    def __init__(self, where, value, sup_plus, sup_minus, inf_plus, inf_minus):
      self.where = np.array(where)
      self.value = value
      self.sup_plus = np.array(sup_plus)
      self.sup_minus = np.array(sup_minus)
      self.inf_plus = np.array(inf_plus)
      self.inf_minus = np.array(inf_minus)

    def find_sup(self, other):
      diff = other-self.where
      sup_sum = diff*(diff > 0)*self.sup_plus + diff*(diff < 0)*self.sup_minus
      return self.value + np.sum(sup_sum)

    def find_inf(self, other):
      diff = other-self.where
      inf_sum = diff*(diff > 0)*self.inf_plus + diff*(diff < 0)*self.inf_minus
      return self.value + np.sum(inf_sum)

  def calculate(self,xs):
    retval = []
    for (i,x) in enumerate(xs):
      supval = min([p.find_sup(np.array(x)/self.scale) for p in self.point_objs])
      infval = max([p.find_inf(np.array(x)/self.scale) for p in self.point_objs])
      if self.maxval is not None:
        supval = min(supval,self.maxval)
        infval = min(infval,self.maxval)
      if self.minval is not None:
        supval = max(supval, self.minval)
        infval = max(infval, self.minval)
      retval.append((supval+infval)/2.0)
    return retval

  def value_bounds(self, point):
    points_greater_than = filter(lambda x: x==point or self.__monotone_rel__(x,point)==1, self.points.keys())
    points_less_than = filter(lambda x: x==point or self.__monotone_rel__(point,x)==1, self.points.keys())
    gtbound = 1e47 if self.maxval is None and points_greater_than else self.maxval
    ltbound = -1e47 if self.minval is None and points_less_than else self.minval
    for p in points_greater_than:
      gtbound = min(self.points[p],gtbound)
    for p in points_less_than:
      ltbound = max(self.points[p],ltbound)
    return ltbound, gtbound

  def picture(self,indices,values,labels=['Dimension 1','Dimension 2','Score']):
    from mpl_toolkits.mplot3d import Axes3D
    from matplotlib import cm
    import matplotlib.pyplot as plt
    
    xs = []
    ys = []
    epoints = []
    dim1 = indices[0]
    dim2 = indices[1]
    # Get the points to evaluate at
    for x in np.linspace(self.bounds[dim1][0],self.bounds[dim1][1],50):
      for y in np.linspace(self.bounds[dim2][0],self.bounds[dim2][1],50):
        xs.append(x)
        ys.append(y)
        epoint = []
        for i in xrange(self.dim):
          if i==indices[0]:
            epoint.append(x)
          elif i==indices[1]:
            epoint.append(y)
          else:
            epoint.append(values[i])
        epoints.append(epoint)
    
    zs = self.calculate(epoints)
    fig = plt.figure()
    ax = fig.gca(projection='3d')
    ax.plot_trisurf(xs, ys, zs, cmap=cm.jet, linewidth=0.2)
    ax.set_xlabel(labels[0])
    ax.set_ylabel(labels[1])
    ax.set_zlabel(labels[2])
    plt.show()


if __name__=='__main__':
  from random import *
  from math import floor
  done = False
  while not done:
    try:
      phsh = {(0,0,1): 0.0, (1,1,0): 100.0}
      for i in xrange(98):
        p = [0,0,0]
        for j in xrange(3):
          p[j] = random()
        v = floor(40*np.sqrt(((p[0]+1-p[2])/2.0)))+floor(20*np.sqrt(p[0]*p[1]))+floor(30*p[1]*(1-p[2]))+floor(uniform(0,10))
        phsh[tuple(p)]=v
      m=create(phsh,[1,1,-1],minval=0,maxval=100) 
      done=True
    except MonotoneError as m:
      continue
  ps = phsh.keys()
  calcs = m.calculate(ps)
  for p,v in zip(ps,calcs):
    #if abs(phsh[p]-v) > 1e-4:
    #  print p,phsh[p],v
    print p,phsh[p],v

  #vals = np.linspace(0,1,1000)
  #ys = m.calculate(vals)
  #import matplotlib.pyplot as plt
  #plt.plot(vals,ys)
  #plt.scatter(ps,phsh.values(),s=50)
  #plt.show()
  m.picture([1,2],[0.5,0,0])