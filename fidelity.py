import numpy as np
import torch
from torch.utils.data import DataLoader
from scipy.optimize import minimize
from scipy.linalg import eigvalsh

import copy, time, math
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D



# Exact classical fidelity

def int2basestr(n, base, l=0):
    """Convert int n into a b-nary list of size l e.g. returns [0, 1, 0] for
    (2, 2, l=3)

    Args:
        n (int) : Integer to convert to a b-nary representation
        b (int) : Base of the b-nary representation e.g. 2 -> {0, 1},
                  3 -> {0, 1, 2}
        l (int) : Length of the b-nary list, if precision is not enough, 
                  it overflows

    Returns:
        (list) : List of size l? i.e. the b-nary representation of n
    """
    d = int(n % base)
    if d == n:
        return [0 for _ in range(l-1)] + [d]
    else:
        a = int2basestr(int((n-d)/base), base) + [d]
        return [0 for _ in range(l-len(a))] + a

def basestr2int(st, base):
    return sum([st[i] * base**(len(st)-i-1) for i in range(len(st))])


# Exact classical fidelity for permutation invariant systems
def binom(p,q, c=1.):
    [p,q] = [max(p,q),min(p,q)]
    for nq in range(q):
        c *= (p+nq+1)/(nq+1)
    return c

def ListUniqueOutcomes(Nq, Na):
    outcomes = [[]]
    for nq in range(Nq):
        prev = len(outcomes)
        
        for na in range(Na):
            i = 0
            if len(outcomes[0]) == 0:
                outcomes.append([na])
            else:
                while na >= outcomes[i][0]:
                    outcomes.append([na]+outcomes[i])
                    i += 1
                    if i >= prev:
                        break
        outcomes = outcomes[prev:]
    return outcomes


def GetMultiP(outcome, probability, Nq, Na):
    p = [0 for _ in range(Na)]
    for nq in range(Nq):
        p[outcome[nq]] += 1
    q = np.cumsum(p)

    for na in range(Na-1):
        probability = binom(p[na+1], q[na], c=probability)

    return probability


def GetUniqueProbabilities(gen1, gen2, print_time=0):

    Nq = gen1.Nq
    Na = gen1.Na
    outcomes = ListUniqueOutcomes(Nq, Na)

    if binom(Nq,Na-1) != len(outcomes):
        print('Incorrect number of outcomes generated')
        return (0, 0)

    No = len(outcomes)


    OutP = []

    t = time.time()
    printt = t
    for no in range(No):
        o = outcomes[no].copy()
        OutPl = outcomes[no].copy()

        # POVM Probability
        p = gen1.p(o)
        OutPl.append(GetMultiP(o, p, Nq, Na))
        
        # Transformer Probability
        p = gen2.p(o)
        OutPl.append(GetMultiP(o, p, Nq, Na))
        
        OutP.append(OutPl)


        if (0 < print_time) & (print_time < (time.time() - printt)):
            print('%i%s complete'%(100.*(no+1)/No, '%'))
            printt = time.time()
    return OutP

def ClFid_perminv(gen1, gen2, print_time = 0, verbose=True):
    with torch.no_grad():
        Nq = gen1.Nq
        Na = gen1.Na

        OutP = GetUniqueProbabilities(gen1, gen2, print_time)
        OutP = np.array(OutP)

        N1 = sum(OutP[:,Nq])
        N2 = sum(OutP[:,Nq+1])

        OutP[:, Nq] = OutP[:, Nq]/N1
        OutP[:, Nq+1] = OutP[:, Nq+1]/N2

        if verbose:
            OutP = OutP[np.flip(OutP[:, Nq].argsort())]
            print('Norm 1: ', N1)
            print('Norm 2: ', N2)
            print(OutP[:10, Nq:])
        return sum(np.sqrt(OutP[:, Nq]*OutP[:, Nq+1]))


# Retrieve density matrix element

def POVMProbTable(gen):
    """Build POVM probability table using the generator

    Args:
        gen (nn.Module) : Generative model under which to calculate the 
                          probabilities for all possible POVM outcomes
    Returns:
        (np.ndarray) : Shape (Na**Nq, 1) with prob. for each possible possible
                       tensor product POVM outcome
    """
    t1 = time.time()
    # No. of qubits and no. of POVM elements
    Nq, Na = gen.Nq, gen.Na

    
    # Vector of dimension (Na**Nq x 1) - main place that could be taking too
    # Note that the samples are not being batched - batch_size = 1
    probs = np.array([gen.p(int2basestr(n, Na, l=Nq)) for n in range(Na**Nq)],
                    dtype=float)
    t = divmod(time.time() - t1, 60)
    print(f'POVMProbTable : took {t[0]} minutes {t[1]} seconds')
    return probs
    
def GenPOVMProbTable(gen, batch_size):
    """Build POVM probability table using the generator

    Args:
        gen (nn.Module) : Generative model under which to calculate the 
                          probabilities for all possible POVM outcomes
    Returns:
        (np.ndarray) : Shape (Na**Nq, 1) with prob. for each possible possible
                       tensor product POVM outcome
    """
    t1 = time.time()
    # No. of qubits and no. of POVM elements
    Nq, Na = gen.Nq, gen.Na
    outcomes, probs = np.arange(Na**Nq), np.ones(Na**Nq)
    n_batches = math.ceil(len(outcomes)/batch_size)

    # Trying to vectorize int2basestr
    v_int2basestr = np.vectorize(int2basestr, otypes=[np.ndarray])
    sequences = np.zeros((len(outcomes), Nq))
    
    # Construct sequences
    ret = v_int2basestr(outcomes, Na, l=Nq)
    for j in range(batch_size):
        sequences[j] = ret[j]
        
    seq_data = DataLoader(sequences, batch_size=batch_size)

    for i, seq_batch in enumerate(seq_data):
        if i == n_batches-1:
            probs[i*batch_size:] = gen.batch_p(
                seq_batch).detach().cpu().numpy()
        else:
            probs[i*batch_size:(i+1)*batch_size] = gen.batch_p(
                seq_batch).detach().cpu().numpy()

    t = divmod(time.time() - t1, 60)
    print(f'GenPOVMProbTable : took {t[0]} minutes {t[1]} seconds')
    
    # Vector of dimension (Na**Nq x 1) - main place that could be taking too
    # Note that the samples are not being batched - batch_size = 1
    return probs


def ClFid(ptab1, ptab2):
    return np.sum(np.sqrt(ptab1*ptab2))


def ClFidEst(gen1, gen2, Ns=1000, print_time=10, samples=None):
    p = 0.
    Nq = gen1.Nq
    Na = gen1.Na

    if len(samples) == 0:
        outcomes = gen1.samples(Ns)
    else:
        outcomes = samples


    t = time.time()
    for ns in range(Ns):
        p += np.sqrt(gen2.p(outcomes[ns])/gen1.p(outcomes[ns]))
        if (time.time()-t) > print_time:
            print('%.1f percent complete: p=%.6f'%(100*(ns+1)/Ns, p/(ns+1)))
            t = time.time()

    return p/Ns

def GetDMFull(ptab, Nq, povm, Ns=0, samples=[]):
    """Reconstruct the density matrix using inversion

    Args:
        ptab (np.ndarray): Probability table of size (Na**Nq, 1) where each
                           element approximates p(i|rho) for all possible POVM
                           outcomes
        Nq (int): No. of qubits
        povm (POVM): 
    """
    Na = povm.Na
    TinvM = povm.TinvM

    Nst = 2**Nq
    dm = np.zeros((Nst, Nst), dtype=complex)

    for st1 in range(Nst):
        for st2 in range(st1, Nst):
            st1_vec = int2basestr(st1, 2, l=Nq)
            st2_vec = int2basestr(st2, 2, l=Nq)

            pa_elem = np.array(ptab, dtype=complex)
            for n in range(Na**Nq):
                o = int2basestr(n, Na, l=Nq)
                for nq in range(Nq):
                    pa_elem[n] *= TinvM[o[nq], st1_vec[nq], st2_vec[nq]]
            dm[st1, st2] = np.sum(pa_elem)
            dm[st2, st1] = np.conj(dm[st1, st2])
    return dm

def plotDM(dm, Nq, figax=None, axis_labels=True):
    xedges = np.arange(0, 2**Nq+1)
    yedges = np.arange(0, 2**Nq+1)

    # Construct arrays for the anchor positions of the 16 bars.
    xpos, ypos = np.meshgrid(xedges[:-1], yedges[:-1], indexing="ij")
    xpos = xpos.ravel()
    ypos = ypos.ravel()
    zpos = 0

    # Construct arrays with the dimensions for the 16 bars.
    dx = dy = np.ones_like(zpos)

    dz = []
    for i in range(2**Nq):
        for j in range(2**Nq):
            dz.append(abs(dm[i, j]))

    if figax is None:
        fig = plt.figure()
        ax = fig.add_subplot(111, projection='3d')
    else:
        (fig, ax) = figax


    ax.bar3d(xpos, ypos, zpos, dx, dy, dz)

    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_zticks([0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6])

    ax.set_xbound(-0.2, 2**Nq+0.2)
    ax.set_ybound(-0.2, 2**Nq+0.2)
    ax.set_zbound(0, 0.5)

    if axis_labels:
        ax.set_xticks([0.5, 2**Nq-0.5])
        ax.set_xticklabels(['0'*Nq, '1'*Nq])
        ax.tick_params(axis='x', pad=-10, labelsize=12)
        plt.setp( ax.xaxis.get_majorticklabels(), rotation=52, ha="right")

        ax.set_yticks([0.5, 2**Nq-0.5])
        ax.set_yticklabels(['0'*Nq, '1'*Nq])
        ax.tick_params(axis='y', pad=-8, labelsize=12)
        plt.setp( ax.yaxis.get_majorticklabels(), rotation=-14, ha="left")
    return fig, ax


def WeightedDM(weights, dm8):
    dm = 0*np.array(dm8[0])
    for i in range(8):
        dm += weights[i]*dm8[i]
    return dm


def MaxNegEig(weights, dm8):
    weights = np.append(np.array(weights), 1-sum(weights))
    dm = WeightedDM(weights, dm8)
    w = eigvalsh(dm)
    return max(0, -min(w.real))

def GetBestDM(dm8):
    t1 = time.time()
    x0 = np.full((7), 1/8)
    bnds = ((0, None), (0, None), (0, None), (0, None), (0, None), (0, None),
            (0, None))
    cons = ({'type': 'ineq', 'fun': lambda x:  1-sum(x)})
    res = minimize(MaxNegEig, x0, args=(dm8), bounds=bnds, constraints=cons)
    weights = np.append(res.x, 1-sum(res.x))
    dm = WeightedDM(weights, dm8)
    t = divmod(time.time() - t1, 60)
    print(f'GetBestDM : took {t[0]} minutes {t[1]} seconds')
    return weights, res.fun, dm/np.trace(dm)
